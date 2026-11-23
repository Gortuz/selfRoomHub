package dev.selfroomhub.panel

import android.content.BroadcastReceiver
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.graphics.Bitmap
import android.media.AudioManager
import android.media.MediaMetadata
import android.media.session.MediaController
import android.media.session.MediaSessionManager
import android.media.session.PlaybackState
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.service.notification.NotificationListenerService
import android.util.Base64
import android.util.Log
import android.view.KeyEvent
import org.json.JSONArray
import org.json.JSONObject
import java.io.ByteArrayOutputStream
import java.net.HttpURLConnection
import java.net.URL
import java.security.MessageDigest
import java.util.concurrent.Executors
import kotlin.math.roundToInt

/** Publica en el backend lo que suena en el telefono (PUT /now-playing). */
class MediaListenerService : NotificationListenerService() {
    private val main = Handler(Looper.getMainLooper())
    private val io = Executors.newSingleThreadExecutor()
    private lateinit var manager: MediaSessionManager
    private lateinit var component: ComponentName

    private var controllers: List<MediaController> = emptyList()
    private var current: MediaController? = null
    private var lastArtHash: String? = null
    private var connected = false

    private lateinit var audio: AudioManager
    @Volatile private var commandThread: Thread? = null
    @Volatile private var commandConn: HttpURLConnection? = null
    private var lastCommandId = 0L
    private var volumeReceiverRegistered = false

    private val volumeReceiver = object : BroadcastReceiver() {
        override fun onReceive(context: Context?, intent: Intent?) {
            if (intent?.getIntExtra(EXTRA_STREAM_TYPE, -1) != AudioManager.STREAM_MUSIC) return
            // Debounce propio: no pisa el de metadata.
            main.removeCallbacks(sendRunnable)
            main.postDelayed(sendRunnable, 300)
        }
    }

    private val sessionsListener =
        MediaSessionManager.OnActiveSessionsChangedListener { list -> onSessions(list ?: emptyList()) }

    private val callback = object : MediaController.Callback() {
        override fun onMetadataChanged(metadata: MediaMetadata?) = scheduleSend()
        override fun onPlaybackStateChanged(state: PlaybackState?) {
            // Puede cambiar cual sesion es la "activa" (la que esta en PLAYING).
            pickCurrent()
            scheduleSend()
        }
        override fun onSessionDestroyed() = refresh()
    }

    private val sendRunnable = Runnable { send() }
    private val periodic = object : Runnable {
        override fun run() {
            if (isPlaying(current)) scheduleSend()
            main.postDelayed(this, 60_000)
        }
    }

    override fun onListenerConnected() {
        connected = true
        manager = getSystemService(MediaSessionManager::class.java)
        audio = getSystemService(AudioManager::class.java)
        component = ComponentName(this, MediaListenerService::class.java)
        try {
            manager.addOnActiveSessionsChangedListener(sessionsListener, component, main)
        } catch (e: SecurityException) {
            Log.w(TAG, "sin acceso a notificaciones", e)
            return
        }
        registerVolume()
        startCommands()
        refresh()
        main.removeCallbacks(periodic)
        main.postDelayed(periodic, 60_000)
    }

    override fun onListenerDisconnected() {
        connected = false
        stopCommands()
        unregisterVolume()
        release()
        runCatching { manager.removeOnActiveSessionsChangedListener(sessionsListener) }
        main.removeCallbacksAndMessages(null)
    }

    override fun onDestroy() {
        stopCommands()
        unregisterVolume()
        release()
        main.removeCallbacksAndMessages(null)
        io.shutdown()
        super.onDestroy()
    }

    private fun refresh() {
        val list = try {
            manager.getActiveSessions(component)
        } catch (e: SecurityException) {
            Log.w(TAG, "getActiveSessions denegado", e)
            emptyList()
        }
        onSessions(list)
    }

    private fun onSessions(list: List<MediaController>) {
        release()
        controllers = list
        list.forEach { it.registerCallback(callback, main) }
        pickCurrent()
        scheduleSend()
    }

    private fun release() {
        controllers.forEach { runCatching { it.unregisterCallback(callback) } }
        controllers = emptyList()
        current = null
    }

    /** Prefiere la sesion en PLAYING; si no hay, la mas reciente (primera de la lista). */
    private fun pickCurrent() {
        current = controllers.firstOrNull { isPlaying(it) } ?: controllers.firstOrNull()
    }

    private fun isPlaying(c: MediaController?): Boolean =
        c?.playbackState?.state == PlaybackState.STATE_PLAYING

    private fun scheduleSend() {
        main.removeCallbacks(sendRunnable)
        main.postDelayed(sendRunnable, 500)
    }

    /** Corre en el hilo principal: arma el JSON y delega la red al executor. */
    private fun send() {
        if (!connected) return
        val c = current
        val json = JSONObject()
        json.put("volume", volumePercent())
        if (c == null) {
            json.put("playing", false)
            lastArtHash = null
        } else {
            val md = c.metadata
            json.put("playing", isPlaying(c))
            json.put("title", md?.text(MediaMetadata.METADATA_KEY_TITLE, MediaMetadata.METADATA_KEY_DISPLAY_TITLE))
            json.put("artist", md?.text(MediaMetadata.METADATA_KEY_ARTIST, MediaMetadata.METADATA_KEY_ALBUM_ARTIST))
            json.put("album", md?.text(MediaMetadata.METADATA_KEY_ALBUM))
            json.put("app", c.packageName)
            json.put("art_base64", md?.let { artIfChanged(it) } ?: JSONObject.NULL)
        }
        val body = json.toString()
        val hash = lastArtHash
        io.execute {
            if (!put(body)) {
                // Que el siguiente envio vuelva a incluir la portada.
                if (hash != null && lastArtHash == hash) lastArtHash = null
            }
        }
    }

    private fun volumePercent(): Int {
        val max = audio.getStreamMaxVolume(AudioManager.STREAM_MUSIC).coerceAtLeast(1)
        return (audio.getStreamVolume(AudioManager.STREAM_MUSIC) * 100f / max).roundToInt()
    }

    private fun registerVolume() {
        if (volumeReceiverRegistered) return
        val filter = IntentFilter(VOLUME_CHANGED_ACTION)
        if (Build.VERSION.SDK_INT >= 33) {
            registerReceiver(volumeReceiver, filter, Context.RECEIVER_NOT_EXPORTED)
        } else {
            registerReceiver(volumeReceiver, filter)
        }
        volumeReceiverRegistered = true
    }

    private fun unregisterVolume() {
        if (!volumeReceiverRegistered) return
        runCatching { unregisterReceiver(volumeReceiver) }
        volumeReceiverRegistered = false
    }

    // --- Ordenes de reproduccion (long-poll a GET /media/commands) ---

    private fun startCommands() {
        if (commandThread?.isAlive == true) return
        val t = Thread({ commandLoop() }, "media-commands")
        t.isDaemon = true
        commandThread = t
        t.start()
    }

    private fun stopCommands() {
        val t = commandThread ?: return
        commandThread = null
        t.interrupt()
        runCatching { commandConn?.disconnect() }
    }

    private fun commandLoop() {
        val me = Thread.currentThread()
        while (commandThread === me && !me.isInterrupted) {
            var pause = 0L
            try {
                val token = Settings.token(this)
                if (token == null) {
                    pause = 30_000
                } else {
                    val conn = URL(
                        Settings.baseUrl(this) + "/media/commands?after=$lastCommandId&wait=25"
                    ).openConnection() as HttpURLConnection
                    commandConn = conn
                    try {
                        conn.connectTimeout = 5000
                        conn.readTimeout = 35000
                        conn.setRequestProperty("Authorization", "Bearer $token")
                        val code = conn.responseCode
                        if (code == 401) {
                            Log.w(TAG, "GET /media/commands -> 401 (token invalido)")
                            pause = 30_000
                        } else if (code !in 200..299) {
                            Log.w(TAG, "GET /media/commands -> $code")
                            pause = 3_000
                        } else {
                            val text = conn.inputStream.bufferedReader().use { it.readText() }
                            handleCommands(JSONArray(text))
                        }
                    } finally {
                        conn.disconnect()
                    }
                }
            } catch (e: InterruptedException) {
                return
            } catch (e: Exception) {
                if (commandThread !== me) return
                Log.w(TAG, "GET /media/commands fallo: ${e.message}")
                pause = 3_000
            }
            if (pause > 0) {
                try {
                    Thread.sleep(pause)
                } catch (e: InterruptedException) {
                    return
                }
            }
        }
    }

    private fun handleCommands(arr: JSONArray) {
        for (i in 0 until arr.length()) {
            val o = arr.getJSONObject(i)
            val id = o.optLong("id", 0)
            if (id > lastCommandId) lastCommandId = id
            val action = o.optString("action")
            val value = if (o.isNull("value")) null else o.optDouble("value")
            main.post {
                try {
                    execute(action, value)
                } catch (e: Exception) {
                    Log.w(TAG, "orden $action fallo", e)
                }
            }
        }
    }

    /** Corre en el hilo principal. */
    private fun execute(action: String, value: Double?) {
        if (!connected) return
        val tc = current?.transportControls
        when (action) {
            "toggle" -> if (isPlaying(current)) tc?.pause() else play(tc)
            "play" -> play(tc)
            "pause" -> tc?.pause()
            "next" -> tc?.skipToNext()
            "previous" -> tc?.skipToPrevious()
            "volume" -> if (value != null) {
                val max = audio.getStreamMaxVolume(AudioManager.STREAM_MUSIC)
                val v = (value.coerceIn(0.0, 100.0) / 100.0 * max).roundToInt()
                audio.setStreamVolume(AudioManager.STREAM_MUSIC, v, 0)
            }
            else -> Log.w(TAG, "orden desconocida: $action")
        }
    }

    private fun play(tc: MediaController.TransportControls?) {
        if (tc != null) {
            tc.play()
        } else {
            // Sin sesion activa: que la ultima app de musica reanude.
            audio.dispatchMediaKeyEvent(KeyEvent(KeyEvent.ACTION_DOWN, KeyEvent.KEYCODE_MEDIA_PLAY))
            audio.dispatchMediaKeyEvent(KeyEvent(KeyEvent.ACTION_UP, KeyEvent.KEYCODE_MEDIA_PLAY))
        }
    }

    private fun MediaMetadata.text(vararg keys: String): Any {
        for (k in keys) getString(k)?.takeIf { it.isNotBlank() }?.let { return it }
        return JSONObject.NULL
    }

    private fun artIfChanged(md: MediaMetadata): String? {
        val bmp = md.getBitmap(MediaMetadata.METADATA_KEY_ALBUM_ART)
            ?: md.getBitmap(MediaMetadata.METADATA_KEY_ART)
            ?: md.getBitmap(MediaMetadata.METADATA_KEY_DISPLAY_ICON)
            ?: return null
        val bytes = encode(bmp)
        val hash = MessageDigest.getInstance("SHA-1").digest(bytes)
            .joinToString("") { "%02x".format(it) }
        if (hash == lastArtHash) return null
        lastArtHash = hash
        return Base64.encodeToString(bytes, Base64.NO_WRAP)
    }

    private fun encode(src: Bitmap): ByteArray {
        val max = 600
        val scale = minOf(1f, max.toFloat() / maxOf(src.width, src.height))
        val bmp = if (scale < 1f) {
            Bitmap.createScaledBitmap(
                src, (src.width * scale).toInt().coerceAtLeast(1),
                (src.height * scale).toInt().coerceAtLeast(1), true,
            )
        } else src
        val out = ByteArrayOutputStream()
        // JPEG no tiene alfa: se aplana si hace falta.
        bmp.compress(Bitmap.CompressFormat.JPEG, 85, out)
        return out.toByteArray()
    }

    private fun put(body: String): Boolean {
        val token = Settings.token(this) ?: return false
        return try {
            val conn = URL(Settings.baseUrl(this) + "/now-playing").openConnection() as HttpURLConnection
            try {
                conn.requestMethod = "PUT"
                conn.connectTimeout = 5000
                conn.readTimeout = 10000
                conn.doOutput = true
                conn.setRequestProperty("Authorization", "Bearer $token")
                conn.setRequestProperty("Content-Type", "application/json; charset=utf-8")
                conn.outputStream.use { it.write(body.toByteArray(Charsets.UTF_8)) }
                val code = conn.responseCode
                if (code !in 200..299) Log.w(TAG, "PUT /now-playing -> $code")
                code in 200..299
            } finally {
                conn.disconnect()
            }
        } catch (e: Exception) {
            Log.w(TAG, "PUT /now-playing fallo: ${e.message}")
            false
        }
    }

    private companion object {
        const val TAG = "MediaListener"
        const val VOLUME_CHANGED_ACTION = "android.media.VOLUME_CHANGED_ACTION"
        const val EXTRA_STREAM_TYPE = "android.media.EXTRA_VOLUME_STREAM_TYPE"
    }
}
