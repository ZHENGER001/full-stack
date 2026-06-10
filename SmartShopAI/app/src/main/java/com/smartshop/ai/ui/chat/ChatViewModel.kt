package com.smartshop.ai.ui.chat

import android.net.Uri
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.smartshop.ai.data.cart.CartRepository
import com.smartshop.ai.data.chat.AiChatEvent
import com.smartshop.ai.data.chat.ChatHistoryRepository
import com.smartshop.ai.data.chat.AiChatRepository
import com.smartshop.ai.data.model.BatchCartContent
import com.smartshop.ai.data.model.ChatMessage
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asSharedFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import org.json.JSONArray
import org.json.JSONObject
import javax.inject.Inject

@HiltViewModel
class ChatViewModel @Inject constructor(
    private val chatRepository: AiChatRepository,
    private val cartRepository: CartRepository,
    private val chatHistoryRepository: ChatHistoryRepository
) : ViewModel() {

    private val greetingMessage = ChatMessage(
        content = "你好！我是SmartShop AI智能导购助手。我可以帮你推荐商品、对比产品，也可以根据图片识别并推荐相关商品。",
        isUser = false
    )

    private val _messages = MutableStateFlow(
        chatHistoryRepository.loadMessages().ifEmpty { listOf(greetingMessage) }
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

    fun sendMessage(text: String = _inputText.value, imageUri: Uri? = null, displayText: String? = null) {
        if (text.isBlank() && imageUri == null) return

        val normalizedText = text.trim()
        val visibleText = displayText?.trim()?.ifBlank { null } ?: normalizedText
        setMessages(
            _messages.value + ChatMessage(
                content = visibleText.ifBlank { "请根据这张图片推荐相关商品" },
                isUser = true,
                imageUri = imageUri?.toString()
            )
        )
        _inputText.value = ""
        _isTyping.value = true

        val assistantMessageId = java.util.UUID.randomUUID().toString()
        setMessages(
            _messages.value + ChatMessage(
                id = assistantMessageId,
                content = "",
                isUser = false,
                isLoading = true
            )
        )

        viewModelScope.launch {
            val cartContext = runCatching { cartRepository.getCart() }.getOrDefault(emptyList())
            chatRepository.streamAssistantReply(normalizedText, imageUri, cartContext).collect { event ->
                when (event) {
                    is AiChatEvent.Delta -> appendAssistantTextAnimated(assistantMessageId, event.text)
                    is AiChatEvent.Products -> updateAssistantMessage(assistantMessageId) {
                        it.copy(productRecommendations = event.products)
                    }
                    is AiChatEvent.Alternatives -> updateAssistantMessage(assistantMessageId) {
                        it.copy(productRecommendations = event.products)
                    }
                    is AiChatEvent.Comparison -> updateAssistantMessage(assistantMessageId) {
                        it.copy(comparison = event.comparison, isLoading = false)
                    }
                    is AiChatEvent.BatchCart -> updateAssistantMessage(assistantMessageId) {
                        it.copy(batchCart = event.batchCart, isLoading = false)
                    }
                    is AiChatEvent.Actions -> updateAssistantMessage(assistantMessageId) {
                        it.copy(actions = event.actions)
                    }
                    is AiChatEvent.Cart -> updateAssistantMessage(assistantMessageId) {
                        it.copy(cartItems = event.items, cartTotalAmount = event.totalAmount)
                    }
                    is AiChatEvent.OrderStatus -> {
                        updateAssistantMessage(assistantMessageId) {
                            it.copy(orderStatusText = event.message, isLoading = false)
                        }
                        if (event.status == "paid") {
                            runCatching { cartRepository.getCart() }
                        }
                    }
                    AiChatEvent.Done -> _isTyping.value = false
                }
            }
        }
    }

    suspend fun transcribeVoice(uri: Uri): VoiceTranscriptionResult =
        runCatching { chatRepository.transcribeAudio(uri) }
            .fold(
                onSuccess = { text ->
                    if (text.isNullOrBlank()) {
                        VoiceTranscriptionResult(
                            errorMessage = "后端 ASR 未配置或没有识别到语音，请检查 ASR_PROVIDER/ASR_BASE_URL/ASR_API_KEY"
                        )
                    } else {
                        VoiceTranscriptionResult(text = text.trim())
                    }
                },
                onFailure = {
                    VoiceTranscriptionResult(errorMessage = "语音转写失败，请稍后再试")
                }
            )

    fun requestAddToCart(productId: String) {
        sendMessage(text = "加入购物车:$productId", displayText = "加入购物车")
    }

    fun confirmBatchCart(batchCart: BatchCartContent, selectedSkuIds: Map<String, String>) {
        val items = JSONArray()
        batchCart.items.forEach { item ->
            val skuId = selectedSkuIds[item.productId] ?: item.selectedSkuId
            if (!skuId.isNullOrBlank()) {
                items.put(
                    JSONObject().apply {
                        put("product_id", item.productId)
                        put("sku_id", skuId)
                        put("quantity", item.quantity)
                    }
                )
            }
        }
        val payload = JSONObject().apply {
            put("batch_id", batchCart.batchId)
            put("items", items)
        }
        sendMessage(
            text = "$BATCH_CART_CONFIRM_PREFIX${payload}",
            displayText = "确认加入购物车"
        )
    }

    private suspend fun appendAssistantTextAnimated(messageId: String, text: String) {
        if (text.isBlank()) {
            updateAssistantMessage(messageId) { it.copy(content = it.content + text, isLoading = false) }
            return
        }

        text.chunked(TYPING_CHUNK_SIZE).forEach { chunk ->
            updateAssistantMessage(messageId) {
                it.copy(content = it.content + chunk, isLoading = false)
            }
            if (chunk.any { it != '\n' }) {
                delay(TYPING_CHUNK_DELAY_MS)
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
        setMessages(
            _messages.value.map { message ->
                if (message.id == messageId) transform(message) else message
            }
        )
    }

    private fun setMessages(messages: List<ChatMessage>) {
        _messages.value = messages
        chatHistoryRepository.saveMessages(messages)
    }

    private companion object {
        const val BATCH_CART_CONFIRM_PREFIX = "__batch_cart_confirm__:"
        const val TYPING_CHUNK_SIZE = 2
        const val TYPING_CHUNK_DELAY_MS = 18L
    }
}

data class VoiceTranscriptionResult(
    val text: String = "",
    val errorMessage: String? = null
)
