package com.smartshop.ai.data.chat

import android.content.Context
import com.smartshop.ai.data.model.ChatAction
import com.smartshop.ai.data.model.ChatMessage
import com.smartshop.ai.data.model.Product
import dagger.hilt.android.qualifiers.ApplicationContext
import org.json.JSONArray
import org.json.JSONObject
import javax.inject.Inject
import javax.inject.Singleton

@Singleton
class ChatHistoryRepository @Inject constructor(
    @ApplicationContext context: Context
) {
    private val prefs = context.getSharedPreferences("smartshop_ai_chat_history", Context.MODE_PRIVATE)

    fun loadMessages(): List<ChatMessage> {
        val raw = prefs.getString(KEY_MESSAGES, null).orEmpty()
        if (raw.isBlank()) return emptyList()
        return runCatching {
            val array = JSONArray(raw)
            (0 until array.length()).mapNotNull { index ->
                array.optJSONObject(index)?.toChatMessage()
            }
        }.getOrDefault(emptyList())
    }

    fun saveMessages(messages: List<ChatMessage>) {
        val persisted = messages
            .filterNot { it.isLoading }
            .takeLast(MAX_MESSAGES)
        val array = JSONArray()
        persisted.forEach { array.put(it.toJson()) }
        prefs.edit().putString(KEY_MESSAGES, array.toString()).apply()
    }

    private fun ChatMessage.toJson(): JSONObject = JSONObject().apply {
        put("id", id)
        put("content", content)
        put("isUser", isUser)
        put("timestamp", timestamp)
        put("imageUri", imageUri)
        put("products", JSONArray().also { array ->
            productRecommendations.forEach { array.put(it.toJson()) }
        })
        put("actions", JSONArray().also { array ->
            actions.forEach { array.put(it.toJson()) }
        })
    }

    private fun JSONObject.toChatMessage(): ChatMessage =
        ChatMessage(
            id = optString("id"),
            content = optString("content"),
            isUser = optBoolean("isUser"),
            timestamp = optLong("timestamp"),
            imageUri = optString("imageUri").ifBlank { null },
            productRecommendations = optJSONArray("products").toProductList(),
            actions = optJSONArray("actions").toActionList()
        )

    private fun Product.toJson(): JSONObject = JSONObject().apply {
        put("id", id)
        put("name", name)
        put("description", description)
        put("price", price)
        put("originalPrice", originalPrice)
        put("imageUrl", imageUrl)
        put("category", category)
        put("categoryId", categoryId)
        put("brand", brand)
        put("rating", rating.toDouble())
        put("reviewCount", reviewCount)
        put("aiComment", aiComment)
        put("inStock", inStock)
        put("specs", JSONObject(specs))
    }

    private fun JSONObject.toProduct(): Product =
        Product(
            id = optString("id"),
            name = optString("name"),
            description = optString("description"),
            price = optDouble("price"),
            originalPrice = if (isNull("originalPrice")) null else optDouble("originalPrice"),
            imageUrl = optString("imageUrl"),
            category = optString("category"),
            categoryId = optString("categoryId"),
            brand = optString("brand"),
            rating = optDouble("rating").toFloat(),
            reviewCount = optInt("reviewCount"),
            specs = optJSONObject("specs").toStringMap(),
            aiComment = optString("aiComment"),
            inStock = optBoolean("inStock", true)
        )

    private fun ChatAction.toJson(): JSONObject = JSONObject().apply {
        put("type", type)
        put("label", label)
        put("productId", productId)
    }

    private fun JSONObject.toChatAction(): ChatAction =
        ChatAction(
            type = optString("type"),
            label = optString("label"),
            productId = optString("productId").ifBlank { null }
        )

    private fun JSONArray?.toProductList(): List<Product> {
        if (this == null) return emptyList()
        return (0 until length()).mapNotNull { index -> optJSONObject(index)?.toProduct() }
    }

    private fun JSONArray?.toActionList(): List<ChatAction> {
        if (this == null) return emptyList()
        return (0 until length()).mapNotNull { index -> optJSONObject(index)?.toChatAction() }
    }

    private fun JSONObject?.toStringMap(): Map<String, String> {
        if (this == null) return emptyMap()
        return keys().asSequence().associateWith { key -> optString(key) }
    }

    private companion object {
        const val KEY_MESSAGES = "messages"
        const val MAX_MESSAGES = 80
    }
}
