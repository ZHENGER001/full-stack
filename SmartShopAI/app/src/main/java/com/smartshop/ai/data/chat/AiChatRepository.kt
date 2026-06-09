package com.smartshop.ai.data.chat

import android.net.Uri
import com.smartshop.ai.data.model.CartItem
import kotlinx.coroutines.flow.Flow
import javax.inject.Inject
import javax.inject.Singleton

@Singleton
class AiChatRepository @Inject constructor(
    private val dataSource: AiChatDataSource
) {
    fun streamAssistantReply(
        text: String,
        imageUri: Uri?,
        cartContext: List<CartItem> = emptyList()
    ): Flow<AiChatEvent> = dataSource.streamAssistantReply(text, imageUri, cartContext)

    suspend fun transcribeAudio(uri: Uri): String? = dataSource.transcribeAudio(uri)
}
