package com.smartshop.ai.data.auth

import android.content.Context
import androidx.datastore.preferences.core.booleanPreferencesKey
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.stringPreferencesKey
import androidx.datastore.preferences.preferencesDataStore
import com.smartshop.ai.data.model.User
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.map
import javax.inject.Inject
import javax.inject.Singleton

private val Context.authDataStore by preferencesDataStore(name = "smartshop_auth")

data class AuthSession(
    val isLoaded: Boolean = false,
    val user: User? = null
)

@Singleton
class AuthRepository @Inject constructor(
    @ApplicationContext private val context: Context
) {
    private val demoUser = User()

    val session: Flow<AuthSession> = context.authDataStore.data.map { preferences ->
        val isLoggedIn = preferences[KEY_LOGGED_IN] ?: false
        AuthSession(
            isLoaded = true,
            user = if (isLoggedIn) {
                demoUser.copy(
                    username = preferences[KEY_USERNAME] ?: demoUser.username,
                    nickname = preferences[KEY_NICKNAME] ?: demoUser.nickname,
                    avatarUrl = preferences[KEY_AVATAR_URL] ?: demoUser.avatarUrl
                )
            } else {
                null
            }
        )
    }

    suspend fun login(username: String, password: String): Result<User> {
        val trimmedUsername = username.trim()
        if (trimmedUsername.isBlank() || password.isBlank()) {
            return Result.failure(IllegalArgumentException("用户名和密码不能为空"))
        }
        if (trimmedUsername != demoUser.username || password != demoUser.password) {
            return Result.failure(IllegalArgumentException("用户名或密码错误"))
        }
        context.authDataStore.edit { preferences ->
            preferences[KEY_LOGGED_IN] = true
            preferences[KEY_USERNAME] = demoUser.username
            preferences[KEY_NICKNAME] = demoUser.nickname
            preferences[KEY_AVATAR_URL] = demoUser.avatarUrl
        }
        return Result.success(demoUser)
    }

    suspend fun logout() {
        context.authDataStore.edit { preferences ->
            preferences.clear()
        }
    }

    suspend fun currentUser(): User =
        session.first().user ?: demoUser

    private companion object {
        val KEY_LOGGED_IN = booleanPreferencesKey("logged_in")
        val KEY_USERNAME = stringPreferencesKey("username")
        val KEY_NICKNAME = stringPreferencesKey("nickname")
        val KEY_AVATAR_URL = stringPreferencesKey("avatar_url")
    }
}
