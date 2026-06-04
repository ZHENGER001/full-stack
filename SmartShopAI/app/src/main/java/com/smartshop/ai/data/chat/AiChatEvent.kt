package com.smartshop.ai.data.chat

import com.smartshop.ai.data.model.ChatAction
import com.smartshop.ai.data.model.Product

sealed interface AiChatEvent {
    data class Delta(val text: String) : AiChatEvent
    data class Products(val products: List<Product>) : AiChatEvent
    data class Actions(val actions: List<ChatAction>) : AiChatEvent
    data object Done : AiChatEvent
}
