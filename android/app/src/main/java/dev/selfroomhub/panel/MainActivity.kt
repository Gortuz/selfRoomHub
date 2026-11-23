package dev.selfroomhub.panel

import android.annotation.SuppressLint
import android.content.Intent
import android.graphics.Color
import android.graphics.Typeface
import android.net.Uri
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.provider.Settings as AndroidSettings
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.view.WindowInsets
import android.view.WindowInsetsController
import android.view.WindowManager
import android.webkit.JavascriptInterface
import android.webkit.WebResourceError
import android.webkit.WebResourceRequest
import android.webkit.WebResourceResponse
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.FrameLayout
import android.widget.TextView
import android.app.Activity
import android.os.Build
import android.window.OnBackInvokedDispatcher

class MainActivity : Activity() {
    private lateinit var webView: WebView
    private lateinit var overlay: TextView
    private val handler = Handler(Looper.getMainLooper())
    private var retryScheduled = false

    private val retry = Runnable {
        retryScheduled = false
        load()
    }

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        overridePendingTransition(0, 0)
        applyIntentConfig(intent)
        applyBrightness()
        if (intent?.getBooleanExtra(EXTRA_WAKE, false) == true) wakeScreen()

        webView = WebView(this).apply {
            setBackgroundColor(Color.BLACK)
            settings.javaScriptEnabled = true
            settings.domStorageEnabled = true
            addJavascriptInterface(Bridge(), "Android")
            webViewClient = object : WebViewClient() {
                override fun onReceivedError(
                    view: WebView, request: WebResourceRequest, error: WebResourceError,
                ) {
                    if (request.isForMainFrame) showWaiting()
                }

                override fun onReceivedHttpError(
                    view: WebView, request: WebResourceRequest, errorResponse: WebResourceResponse,
                ) {
                    if (request.isForMainFrame) showWaiting()
                }

                override fun onPageFinished(view: WebView, url: String?) {
                    if (!retryScheduled) this@MainActivity.overlay.visibility = View.GONE
                }
            }
        }
        overlay = TextView(this).apply {
            setBackgroundColor(Color.BLACK)
            setTextColor(Color.LTGRAY)
            textSize = 22f
            typeface = Typeface.MONOSPACE
            gravity = Gravity.CENTER
            setPadding(48, 48, 48, 48)
            visibility = View.GONE
        }
        val root = FrameLayout(this)
        val match = ViewGroup.LayoutParams.MATCH_PARENT
        root.addView(webView, FrameLayout.LayoutParams(match, match))
        root.addView(overlay, FrameLayout.LayoutParams(match, match))
        setContentView(root)

        if (Build.VERSION.SDK_INT >= 33) {
            // Kiosco: con back predictivo onBackPressed no se invoca; se consume aqui.
            onBackInvokedDispatcher.registerOnBackInvokedCallback(
                OnBackInvokedDispatcher.PRIORITY_DEFAULT,
            ) {}
        }
        hideSystemBars()
        load()
    }

    @Deprecated("Kiosco: no se sale de la app")
    override fun onBackPressed() {
        // Kiosco: no se sale de la app.
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        if (intent.getBooleanExtra(EXTRA_WAKE, false)) wakeScreen()
        if (applyIntentConfig(intent)) load()
    }

    override fun onWindowFocusChanged(hasFocus: Boolean) {
        super.onWindowFocusChanged(hasFocus)
        if (hasFocus) hideSystemBars()
    }

    override fun onResume() {
        super.onResume()
        applyBrightness()
    }

    private fun applyBrightness() {
        val b = Settings.brightness(this)
        window.attributes = window.attributes.apply {
            screenBrightness = if (b < 0f) WindowManager.LayoutParams.BRIGHTNESS_OVERRIDE_NONE else b.coerceIn(0.01f, 1f)
        }
    }

    /** Enciende la pantalla (incluso bloqueada), la mantiene encendida y avisa a la pagina. */
    private fun wakeScreen() {
        if (Build.VERSION.SDK_INT >= 27) {
            setTurnScreenOn(true)
            setShowWhenLocked(true)
        } else {
            @Suppress("DEPRECATION")
            window.addFlags(
                WindowManager.LayoutParams.FLAG_TURN_SCREEN_ON or
                    WindowManager.LayoutParams.FLAG_SHOW_WHEN_LOCKED,
            )
        }
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        if (::webView.isInitialized) {
            webView.evaluateJavascript("window.srhWake && window.srhWake()", null)
        }
    }

    override fun onDestroy() {
        handler.removeCallbacks(retry)
        webView.destroy()
        super.onDestroy()
    }

    /** Guarda token/base_url si llegan como extras. Devuelve true si hubo cambios. */
    private fun applyIntentConfig(intent: Intent?): Boolean {
        val token = intent?.getStringExtra("token")
        val baseUrl = intent?.getStringExtra("base_url")
        if (token.isNullOrBlank() && baseUrl.isNullOrBlank()) return false
        Settings.save(this, token, baseUrl)
        return true
    }

    private fun load() {
        handler.removeCallbacks(retry)
        retryScheduled = false
        val token = Settings.token(this)
        if (token == null) {
            showMessage(
                "Falta configurar el token.\n\n" +
                    "Desde Termux:\n" +
                    "am start -n dev.selfroomhub.panel/.MainActivity --es token <TOKEN>\n\n" +
                    "Acceso a notificaciones (adb):\n" +
                    "cmd notification allow_listener " +
                    "dev.selfroomhub.panel/dev.selfroomhub.panel.MediaListenerService\n" +
                    "o Ajustes > Notificaciones > Acceso a notificaciones.",
            )
            return
        }
        val url = Settings.baseUrl(this) + "/panel/#token=" + Uri.encode(token)
        webView.loadUrl(url)
    }

    private fun showMessage(text: String) {
        overlay.text = text
        overlay.visibility = View.VISIBLE
    }

    private fun showWaiting() {
        showMessage("Esperando al servidor…")
        if (!retryScheduled) {
            retryScheduled = true
            handler.postDelayed(retry, 5000)
        }
    }

    private fun hideSystemBars() {
        window.setDecorFitsSystemWindows(false)
        window.insetsController?.let {
            it.hide(WindowInsets.Type.statusBars() or WindowInsets.Type.navigationBars())
            it.systemBarsBehavior = WindowInsetsController.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE
        }
    }

    private inner class Bridge {
        @JavascriptInterface
        fun openSettings() {
            runOnUiThread {
                startActivity(Intent(AndroidSettings.ACTION_SETTINGS).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
            }
        }

        @JavascriptInterface
        fun setKeepAwake(on: Boolean) {
            runOnUiThread {
                if (on) window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
                else window.clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
            }
        }

        @JavascriptInterface
        fun screenOffTimeout(): Long = try {
            AndroidSettings.System.getLong(contentResolver, AndroidSettings.System.SCREEN_OFF_TIMEOUT, 60000L)
        } catch (e: Exception) {
            60000L
        }

        @JavascriptInterface
        fun setBrightness(value: Float) {
            val v = if (value < 0f) -1f else value.coerceIn(0.01f, 1f)
            Settings.saveBrightness(this@MainActivity, v)
            runOnUiThread { applyBrightness() }
        }

        @JavascriptInterface
        fun getBrightness(): Float = Settings.brightness(this@MainActivity)

        @JavascriptInterface
        fun appVersion(): String = BuildConfigVersion.name(this@MainActivity)
    }
}

const val EXTRA_WAKE = "wake"

private object BuildConfigVersion {
    fun name(ctx: android.content.Context): String =
        ctx.packageManager.getPackageInfo(ctx.packageName, 0).versionName ?: "?"
}
