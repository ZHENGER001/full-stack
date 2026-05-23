package com.smartshop.ai.ui.chat

import android.net.Uri
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.smartshop.ai.data.cart.CartRepository
import com.smartshop.ai.data.chat.AiChatEvent
import com.smartshop.ai.data.chat.AiChatRepository
import com.smartshop.ai.data.model.ChatMessage
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asSharedFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import javax.inject.Inject

@HiltViewModel
class ChatViewModel @Inject constructor(
    private val chatRepository: AiChatRepository,
    private val cartRepository: CartRepository
) : ViewModel() {

    private val _messages = MutableStateFlow(
        listOf(
            ChatMessage(
                content = "你好！我是SmartShop AI智能导购助手。我可以帮你推荐商品、对比产品，也可以根据图片识别并推荐相关商品。",
                isUser = false
            )
        )
    )
    val messages: StateFlow<List<ChatMessage>> = _messages.asStateFlow()

    private val _inputText = MutableStateFlow("")
    val inputText: StateFlow<String> = _inputText.asStateFlow()

    private val _isTyping = MutableStateFlow(false)
    val isTyping: StateFlow<Boolean> = _isTyping.asStateFlow()

    private val _events = MutableSharedFlow<String>()
    val events: SharedFlow<String> = _events.asSharedFlow()

    fun updateInput(text: String) {
        _inputText.value = text
    }

    fun sendMessage(text: String = _inputText.value, imageUri: Uri? = null) {
        if (text.isBlank() && imageUri == null) return

        val normalizedText = text.trim()
        _messages.value = _messages.value + ChatMessage(
            content = normalizedText.ifBlank { "请根据这张图片推荐相关商品" },
            isUser = true,
            imageUri = imageUri?.toString()
        )
        _inputText.value = ""
        _isTyping.value = true

        val assistantMessageId = java.util.UUID.randomUUID().toString()
        _messages.value = _messages.value + ChatMessage(
            id = assistantMessageId,
            content = "",
            isUser = false,
            isLoading = true
        )

        viewModelScope.launch {
            chatRepository.streamAssistantReply(normalizedText, imageUri).collect { event ->
                when (event) {
                    is AiChatEvent.Delta -> updateAssistantMessage(assistantMessageId) {
                        it.copy(content = it.content + event.text, isLoading = false)
                    }
                    is AiChatEvent.Products -> updateAssistantMessage(assistantMessageId) {
                        it.copy(productRecommendations = event.products)
                    }
                    is AiChatEvent.Actions -> updateAssistantMessage(assistantMessageId) {
                        it.copy(actionSuggestions = event.actions)
                    }
                    AiChatEvent.Done -> _isTyping.value = false
                }
            }
        }
    }

    fun addToCart(productId: String) {
        viewModelScope.launch {
            runCatching { cartRepository.addProduct(productId) }
                .onSuccess { _events.emit("已加入购物车") }
                .onFailure { _events.emit("加入购物车失败：${it.message ?: "网络错误"}") }
        }
    }

    private fun updateAssistantMessage(
        messageId: String,
        transform: (ChatMessage) -> ChatMessage
    ) {
        _messages.value = _messages.value.map { message ->
            if (message.id == messageId) transform(message) else message
        }
    }
}
