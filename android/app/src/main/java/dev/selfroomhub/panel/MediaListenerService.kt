package dev.selfroomhub.panel

import android.content.BroadcastReceiver
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.net.Uri
import android.media.AudioManager
import android.media.MediaMetadata
import android.media.session.MediaController
import android.media.session.MediaSessionManager
import android.media.session.PlaybackState
import android.os.Build
import android.app.SearchManager
import android.os.Handler
import android.os.Bundle
import android.os.PowerManager
import android.provider.MediaStore
import android.os.Looper
import android.os.SystemClock
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
    @Volatile private var lastArtHash: String? = null
    // El backend respondió sin portada para la canción actual: reenviarla una vez por canción
    @Volatile private var backendMissingArt = false
    private var artResyncKey: String? = null
    // Solo se tocan desde el executor `io`.
    private var artCacheKey: String? = null
    private var artCacheBytes: ByteArray? = null
    private var artCacheLog: String = ""
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
            checkPlayingTransition()
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
        checkPlayingTransition()
        scheduleSend()
    }

    private var wasPlaying = false

    /** Enciende la pantalla cuando alguna sesion pasa a PLAYING (y antes no habia ninguna). */
    private fun checkPlayingTransition() {
        val now = controllers.any { isPlaying(it) }
        if (now && !wasPlaying) wakeScreen()
        wasPlaying = now
    }

    /**
     * Despierta la pantalla con un wake lock y trae el panel al frente (intent a la actividad).
     * El servicio es un NotificationListener ligado por el sistema; si Android bloquea el inicio
     * de la actividad desde segundo plano, queda solo el wake lock.
     */
    @Suppress("DEPRECATION")
    private fun wakeScreen() {
        runCatching {
            val pm = getSystemService(PowerManager::class.java)
            pm.newWakeLock(
                PowerManager.SCREEN_BRIGHT_WAKE_LOCK or PowerManager.ACQUIRE_CAUSES_WAKEUP,
                "selfRoomHub:wake",
            ).acquire(10_000)
        }.onFailure { Log.w(TAG, "wake lock fallo", it) }
        try {
            startActivity(
                Intent(this, MainActivity::class.java)
                    .putExtra(EXTRA_WAKE, true)
                    .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_REORDER_TO_FRONT),
            )
        } catch (e: Exception) {
            Log.w(TAG, "no se pudo abrir el panel; solo wake lock", e)
        }
    }

    /**
     * Abre una app (p. ej. Spotify, que Android cierra para ahorrar batería) y, unos segundos
     * después, vuelve a poner el panel al frente: la app queda corriendo por detrás.
     */
    private fun launchApp(pkg: String?) {
        if (pkg == null) {
            Log.w(TAG, "launch sin package")
            return
        }
        val intent = packageManager.getLaunchIntentForPackage(pkg)
        if (intent == null) {
            Log.w(TAG, "launch: $pkg no está instalada o no es visible")
            return
        }
        wakeScreen()
        try {
            startActivity(intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
            Log.i(TAG, "launch: abierta $pkg")
        } catch (e: Exception) {
            Log.w(TAG, "launch: no se pudo abrir $pkg", e)
            return
        }
        main.postDelayed({
            runCatching {
                startActivity(
                    Intent(this, MainActivity::class.java)
                        .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_REORDER_TO_FRONT),
                )
            }.onFailure { Log.w(TAG, "launch: no se pudo volver al panel", it) }
        }, PANEL_BACK_DELAY_MS)
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
        var md: MediaMetadata? = null
        json.put("volume", volumePercent())
        if (c == null) {
            json.put("playing", false)
            lastArtHash = null
        } else {
            md = c.metadata
            json.put("playing", isPlaying(c))
            json.put("title", md?.text(MediaMetadata.METADATA_KEY_TITLE, MediaMetadata.METADATA_KEY_DISPLAY_TITLE))
            json.put("artist", md?.text(MediaMetadata.METADATA_KEY_ARTIST, MediaMetadata.METADATA_KEY_ALBUM_ARTIST))
            json.put("album", md?.text(MediaMetadata.METADATA_KEY_ALBUM))
            json.put("app", c.packageName)
            putPosition(json, c, md)
        }
        val withArt = c != null
        io.execute {
            // La portada (posible descarga) se resuelve fuera del hilo principal.
            json.put("art_base64", (if (withArt) md?.let { artIfChanged(it) } else null) ?: JSONObject.NULL)
            val hash = lastArtHash
            if (!put(json.toString())) {
                // Que el siguiente envio vuelva a incluir la portada.
                if (hash != null && lastArtHash == hash) lastArtHash = null
            } else if (backendMissingArt && withArt) {
                // Desincronizados (backend reiniciado o primera canción sin imagen): reenviar ya
                val songKey = json.optString("title") + "|" + json.optString("artist")
                if (songKey != artResyncKey) {
                    artResyncKey = songKey
                    lastArtHash = null
                    main.postDelayed({ scheduleSend() }, 1_000)
                }
            }
        }
    }

    /** Posicion de reproduccion; omite lo que no se conoce. */
    private fun putPosition(json: JSONObject, c: MediaController, md: MediaMetadata?) {
        val st = c.playbackState
        if (st != null && st.position >= 0) {
            json.put("position_ms", st.position)
            json.put(
                "position_at",
                System.currentTimeMillis() - (SystemClock.elapsedRealtime() - st.lastPositionUpdateTime),
            )
            val speed = if (st.playbackSpeed == 0f && st.state == PlaybackState.STATE_PLAYING) 1f else st.playbackSpeed
            json.put("speed", speed.toDouble())
        }
        val dur = md?.getLong(MediaMetadata.METADATA_KEY_DURATION) ?: 0L
        if (dur > 0) json.put("duration_ms", dur)
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
            val query = if (o.isNull("query")) null else o.optString("query").takeIf { it.isNotBlank() }
            val focus = if (o.isNull("focus")) "any" else o.optString("focus", "any")
            val pkg = if (o.isNull("package")) null else o.optString("package").takeIf { it.isNotBlank() }
            main.post {
                try {
                    if (action == "launch") launchApp(pkg) else execute(action, value, query, focus)
                } catch (e: Exception) {
                    Log.w(TAG, "orden $action fallo", e)
                }
            }
        }
    }

    /** Corre en el hilo principal. */
    private fun execute(action: String, value: Double?, query: String? = null, focus: String = "any") {
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
            "wake" -> wakeScreen()
            "play_search" -> if (query != null) playSearch(query, focus) else Log.w(TAG, "play_search sin query")
            else -> Log.w(TAG, "orden desconocida: $action")
        }
    }

    private fun searchExtras(query: String, focus: String): Bundle = Bundle().apply {
        when (focus) {
            "artist" -> {
                putString(MediaStore.EXTRA_MEDIA_FOCUS, MediaStore.Audio.Artists.ENTRY_CONTENT_TYPE)
                putString(MediaStore.EXTRA_MEDIA_ARTIST, query)
            }
            "album" -> {
                putString(MediaStore.EXTRA_MEDIA_FOCUS, MediaStore.Audio.Albums.ENTRY_CONTENT_TYPE)
                putString(MediaStore.EXTRA_MEDIA_ALBUM, query)
            }
            "playlist" -> {
                putString(MediaStore.EXTRA_MEDIA_FOCUS, "vnd.android.cursor.item/playlist")
                putString(MediaStore.EXTRA_MEDIA_PLAYLIST, query)
            }
        }
    }

    private fun playSearch(query: String, focus: String) {
        val extras = searchExtras(query, focus)
        val c = controllers.firstOrNull { it.packageName == SPOTIFY } ?: current
        if (c != null) {
            Log.i(TAG, "play_search via controlador ${c.packageName}: \"$query\" ($focus)")
            c.transportControls.playFromSearch(query, extras)
            return
        }
        Log.i(TAG, "play_search via intent a $SPOTIFY: \"$query\" ($focus)")
        wakeScreen()
        startActivity(
            Intent(MediaStore.INTENT_ACTION_MEDIA_PLAY_FROM_SEARCH)
                .setPackage(SPOTIFY)
                .putExtra(SearchManager.QUERY, query)
                .putExtras(extras)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK),
        )
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

    /** Corre en `io`. Devuelve la portada en base64 solo si cambio. */
    private fun artIfChanged(md: MediaMetadata): String? {
        val uris = URI_KEYS.mapNotNull { k -> md.getString(k)?.trim()?.takeIf { it.isNotEmpty() }?.let { k to it } }
        val key = uris.joinToString("|") { it.second }
        val bytes: ByteArray
        if (key.isNotEmpty() && key == artCacheKey && artCacheBytes != null) {
            bytes = artCacheBytes!!
        } else {
            var found: ByteArray? = null
            var label = ""
            for ((k, u) in uris) {
                val bmp = try { fetchBitmap(u) } catch (e: Exception) {
                    Log.w(TAG, "art: fallo $k: ${e.message}")
                    null
                } ?: continue
                if (minOf(bmp.width, bmp.height) < MIN_ART_SIDE) continue
                found = encode(bmp)
                label = "${k.removePrefix("android.media.metadata.")} ${u.take(80)}"
                break
            }
            if (found == null) {
                val (name, bmp) = listOf(
                    "ALBUM_ART" to MediaMetadata.METADATA_KEY_ALBUM_ART,
                    "ART" to MediaMetadata.METADATA_KEY_ART,
                    "DISPLAY_ICON" to MediaMetadata.METADATA_KEY_DISPLAY_ICON,
                ).firstNotNullOfOrNull { (n, k) -> md.getBitmap(k)?.let { n to it } } ?: return null
                found = encode(bmp)
                label = "$name bitmap ${bmp.width}x${bmp.height}"
                // Sin cache: el bitmap ya esta en memoria y el hash evita reenviar.
                artCacheKey = null
                artCacheBytes = null
            } else {
                artCacheKey = key
                artCacheBytes = found
            }
            bytes = found
            val size = BitmapFactory.Options().apply { inJustDecodeBounds = true }
                .also { BitmapFactory.decodeByteArray(found, 0, found.size, it) }
            artCacheLog = "art: $label -> ${size.outWidth}x${size.outHeight}"
            Log.i(TAG, artCacheLog)
        }
        val hash = MessageDigest.getInstance("SHA-1").digest(bytes)
            .joinToString("") { "%02x".format(it) }
        if (hash == lastArtHash) return null
        lastArtHash = hash
        return Base64.encodeToString(bytes, Base64.NO_WRAP)
    }

    private fun fetchBitmap(uri: String): Bitmap? {
        val data: ByteArray = when {
            uri.startsWith("https://") || uri.startsWith("http://") -> download(uri)
            uri.startsWith("spotify:image:") ->
                download("https://i.scdn.co/image/" + uri.removePrefix("spotify:image:"))
            uri.startsWith("content://") || uri.startsWith("android.resource://") ->
                contentResolver.openInputStream(Uri.parse(uri))?.use { readLimited(it) } ?: return null
            else -> return null
        }
        return BitmapFactory.decodeByteArray(data, 0, data.size)
    }

    private fun download(url: String): ByteArray {
        val conn = URL(url).openConnection() as HttpURLConnection
        try {
            conn.connectTimeout = 5000
            conn.readTimeout = 5000
            if (conn.responseCode !in 200..299) error("HTTP ${conn.responseCode}")
            return conn.inputStream.use { readLimited(it) }
        } finally {
            conn.disconnect()
        }
    }

    private fun readLimited(input: java.io.InputStream): ByteArray {
        val out = ByteArrayOutputStream()
        val buf = ByteArray(8192)
        while (true) {
            val n = input.read(buf)
            if (n < 0) break
            out.write(buf, 0, n)
            if (out.size() >= MAX_ART_BYTES) break
        }
        return out.toByteArray()
    }

    private fun encode(src: Bitmap): ByteArray {
        val max = 1000
        val scale = minOf(1f, max.toFloat() / maxOf(src.width, src.height))
        val bmp = if (scale < 1f) {
            Bitmap.createScaledBitmap(
                src, (src.width * scale).toInt().coerceAtLeast(1),
                (src.height * scale).toInt().coerceAtLeast(1), true,
            )
        } else src
        val out = ByteArrayOutputStream()
        // JPEG no tiene alfa: se aplana si hace falta.
        bmp.compress(Bitmap.CompressFormat.JPEG, 90, out)
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
                if (code in 200..299) {
                    // ¿El backend tiene la portada de lo que suena? (pudo reiniciarse o perderla)
                    val resp = runCatching { JSONObject(conn.inputStream.bufferedReader().readText()) }.getOrNull()
                    backendMissingArt = resp != null && !resp.isNull("title") && resp.isNull("art_url")
                }
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
        private const val PANEL_BACK_DELAY_MS = 5_000L
        const val TAG = "MediaListener"
        const val SPOTIFY = "com.spotify.music"
        const val MIN_ART_SIDE = 400
        const val MAX_ART_BYTES = 3 * 1024 * 1024
        val URI_KEYS = listOf(
            MediaMetadata.METADATA_KEY_ALBUM_ART_URI,
            MediaMetadata.METADATA_KEY_ART_URI,
            MediaMetadata.METADATA_KEY_DISPLAY_ICON_URI,
        )
        const val VOLUME_CHANGED_ACTION = "android.media.VOLUME_CHANGED_ACTION"
        const val EXTRA_STREAM_TYPE = "android.media.EXTRA_VOLUME_STREAM_TYPE"
    }
}
