package com.smartshop.ai.data.chat

import com.smartshop.ai.data.model.ChatAction
import com.smartshop.ai.data.model.BatchCartContent
import com.smartshop.ai.data.model.CartItem
import com.smartshop.ai.data.model.ComparisonContent
import com.smartshop.ai.data.model.Product

sealed interface AiChatEvent {
    data class Delta(val text: String) : AiChatEvent
    data class Products(val products: List<Product>) : AiChatEvent
    data class Alternatives(val products: List<Product>) : AiChatEvent
    data class Comparison(val comparison: ComparisonContent) : AiChatEvent
    data class BatchCart(val batchCart: BatchCartContent) : AiChatEvent
    data class Actions(val actions: List<ChatAction>) : AiChatEvent
    data class Cart(val items: List<CartItem>, val totalAmount: Double) : AiChatEvent
    data class OrderStatus(
        val status: String,
        val message: String,
        val orderId: String? = null,
        val paymentId: String? = null
    ) : AiChatEvent
    data object Done : AiChatEvent
}
