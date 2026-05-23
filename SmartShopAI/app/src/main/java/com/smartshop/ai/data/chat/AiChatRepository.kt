package com.smartshop.ai.data.chat

import android.net.Uri
import kotlinx.coroutines.flow.Flow
import javax.inject.Inject
import javax.inject.Singleton

@Singleton
class AiChatRepository @Inject constructor(
    private val dataSource: AiChatDataSource
) {
    fun streamAssistantReply(
        text: String,
        imageUri: Uri?
    ): Flow<AiChatEvent> = dataSource.streamAssistantReply(text, imageUri)
}
