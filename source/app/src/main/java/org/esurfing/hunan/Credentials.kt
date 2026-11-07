package org.esurfing.hunan

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec
import java.security.GeneralSecurityException

class CredentialsUnavailable : GeneralSecurityException("凭据不可用，请重新输入密码")

class Credentials(context: Context) {
    private val prefs = context.getSharedPreferences("vault", Context.MODE_PRIVATE)
    private fun key(): SecretKey {
        val store = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        (store.getKey("campus-v1", null) as? SecretKey)?.let { return it }
        return KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore").apply {
            init(KeyGenParameterSpec.Builder("campus-v1", KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM).setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE).build())
        }.generateKey()
    }
    fun save(password: String) {
        fun encryption() = Cipher.getInstance("AES/GCM/NoPadding").apply { init(Cipher.ENCRYPT_MODE, key()) }
        val cipher = try { encryption() } catch(e: GeneralSecurityException) {
            // Only an explicit new-password save may replace a confirmed unusable local credential key.
            if(e !is android.security.keystore.KeyPermanentlyInvalidatedException && e !is java.security.UnrecoverableKeyException) throw e
            KeyStore.getInstance("AndroidKeyStore").apply { load(null); deleteEntry("campus-v1") }
            encryption()
        }
        val encrypted = cipher.doFinal(password.toByteArray(Charsets.UTF_8))
        check(prefs.edit().putString("iv", Base64.encodeToString(cipher.iv, Base64.NO_WRAP))
            .putString("cipher", Base64.encodeToString(encrypted, Base64.NO_WRAP)).commit())
    }
    fun load(): String {
        val data = prefs.getString("cipher", null) ?: return ""
        try {
            val iv = prefs.getString("iv", null) ?: throw CredentialsUnavailable()
            return Cipher.getInstance("AES/GCM/NoPadding").run {
                init(Cipher.DECRYPT_MODE, key(), GCMParameterSpec(128, Base64.decode(iv, Base64.NO_WRAP)))
                String(doFinal(Base64.decode(data, Base64.NO_WRAP)), Charsets.UTF_8)
            }
        } catch (_: Exception) { throw CredentialsUnavailable() }
    }
    fun clear() { prefs.edit().clear().commit() }
}
