package dev.selfroomhub.panel

import android.content.Context
import android.content.SharedPreferences
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKey

/** Token y URL base del backend, guardados cifrados. */
object Settings {
    const val DEFAULT_BASE_URL = "http://127.0.0.1:8000"
    private const val KEY_TOKEN = "token"
    private const val KEY_BASE_URL = "base_url"
    private const val KEY_BRIGHTNESS = "brightness"

    @Volatile
    private var prefs: SharedPreferences? = null

    private fun prefs(context: Context): SharedPreferences =
        prefs ?: synchronized(this) {
            prefs ?: run {
                val app = context.applicationContext
                val key = MasterKey.Builder(app)
                    .setKeyScheme(MasterKey.KeyScheme.AES256_GCM)
                    .build()
                EncryptedSharedPreferences.create(
                    app,
                    "panel_settings",
                    key,
                    EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
                    EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM,
                ).also { prefs = it }
            }
        }

    fun token(context: Context): String? =
        prefs(context).getString(KEY_TOKEN, null)?.takeIf { it.isNotBlank() }

    fun baseUrl(context: Context): String =
        (prefs(context).getString(KEY_BASE_URL, null)?.takeIf { it.isNotBlank() }
            ?: DEFAULT_BASE_URL).trimEnd('/')

    /** Brillo de la ventana (0.01-1) o -1 para el del sistema. */
    fun brightness(context: Context): Float = prefs(context).getFloat(KEY_BRIGHTNESS, -1f)

    fun saveBrightness(context: Context, value: Float) {
        prefs(context).edit().putFloat(KEY_BRIGHTNESS, value).apply()
    }

    fun save(context: Context, token: String?, baseUrl: String?) {
        prefs(context).edit().apply {
            if (!token.isNullOrBlank()) putString(KEY_TOKEN, token.trim())
            if (!baseUrl.isNullOrBlank() && isLocal(baseUrl)) putString(KEY_BASE_URL, baseUrl.trim())
        }.apply()
    }

    // La actividad es pública: cualquier app podría mandar un base_url y llevarse el token.
    // El kiosco solo habla con el backend del mismo teléfono, así que se aceptan únicamente direcciones locales.
    fun isLocal(url: String): Boolean {
        val uri = android.net.Uri.parse(url.trim())
        return (uri.scheme == "http" || uri.scheme == "https") &&
            uri.host in setOf("127.0.0.1", "localhost", "::1", "[::1]")
    }
}
