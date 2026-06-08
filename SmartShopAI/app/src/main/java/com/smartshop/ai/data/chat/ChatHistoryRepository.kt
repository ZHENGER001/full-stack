package com.smartshop.ai.data.chat

import android.content.Context
import com.smartshop.ai.data.model.ChatAction
import com.smartshop.ai.data.model.CartItem
import com.smartshop.ai.data.model.ChatMessage
import com.smartshop.ai.data.model.ComparisonColumn
import com.smartshop.ai.data.model.ComparisonContent
import com.smartshop.ai.data.model.ComparisonRow
import com.smartshop.ai.data.model.ComparisonSection
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
        put("comparison", comparison?.toJson())
        put("actions", JSONArray().also { array ->
            actions.forEach { array.put(it.toJson()) }
        })
        put("cartItems", JSONArray().also { array ->
            cartItems.forEach { array.put(it.toJson()) }
        })
        put("cartTotalAmount", cartTotalAmount)
        put("orderStatusText", orderStatusText)
    }

    private fun JSONObject.toChatMessage(): ChatMessage =
        ChatMessage(
            id = optString("id"),
            content = optString("content"),
            isUser = optBoolean("isUser"),
            timestamp = optLong("timestamp"),
            imageUri = optString("imageUri").ifBlank { null },
            productRecommendations = optJSONArray("products").toProductList(),
            comparison = optJSONObject("comparison")?.toComparisonContent(),
            actions = optJSONArray("actions").toActionList(),
            cartItems = optJSONArray("cartItems").toCartItemList(),
            cartTotalAmount = if (isNull("cartTotalAmount")) null else optDouble("cartTotalAmount"),
            orderStatusText = optString("orderStatusText").ifBlank { null }
        )

    private fun ComparisonContent.toJson(): JSONObject = JSONObject().apply {
        put("title", title)
        put("summary", summary)
        put("columns", JSONArray().also { array ->
            columns.forEach { array.put(it.toJson()) }
        })
        put("rows", JSONArray().also { array ->
            rows.forEach { array.put(it.toJson()) }
        })
        put("sections", JSONArray().also { array ->
            sections.forEach { array.put(it.toJson()) }
        })
        put("recommendation", recommendation)
        put("footnote", footnote)
    }

    private fun ComparisonColumn.toJson(): JSONObject = JSONObject().apply {
        put("label", label)
        put("productId", productId)
    }

    private fun ComparisonRow.toJson(): JSONObject = JSONObject().apply {
        put("dimension", dimension)
        put("values", JSONArray().also { array -> values.forEach { array.put(it) } })
        put("highlightIndex", highlightIndex)
    }

    private fun ComparisonSection.toJson(): JSONObject = JSONObject().apply {
        put("title", title)
        put("productId", productId)
        put("bullets", JSONArray().also { array -> bullets.forEach { array.put(it) } })
    }

    private fun JSONObject.toComparisonContent(): ComparisonContent =
        ComparisonContent(
            title = optString("title"),
            summary = optString("summary"),
            columns = optJSONArray("columns").toComparisonColumns(),
            rows = optJSONArray("rows").toComparisonRows(),
            sections = optJSONArray("sections").toComparisonSections(),
            recommendation = optString("recommendation"),
            footnote = optString("footnote").ifBlank { null }
        )

    private fun JSONObject.toComparisonColumn(): ComparisonColumn =
        ComparisonColumn(
            label = optString("label"),
            productId = optString("productId").ifBlank { optString("product_id") }.ifBlank { null }
        )

    private fun JSONObject.toComparisonRow(): ComparisonRow =
        ComparisonRow(
            dimension = optString("dimension"),
            values = optJSONArray("values").toStringList(),
            highlightIndex = when {
                has("highlightIndex") && !isNull("highlightIndex") -> optInt("highlightIndex")
                has("highlight_index") && !isNull("highlight_index") -> optInt("highlight_index")
                else -> null
            }
        )

    private fun JSONObject.toComparisonSection(): ComparisonSection =
        ComparisonSection(
            title = optString("title"),
            productId = optString("productId").ifBlank { optString("product_id") }.ifBlank { null },
            bullets = optJSONArray("bullets").toStringList()
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

    private fun CartItem.toJson(): JSONObject = JSONObject().apply {
        put("id", id)
        put("productId", productId)
        put("productName", productName)
        put("productImage", productImage)
        put("skuId", skuId)
        put("skuText", skuText)
        put("skuPrice", skuPrice)
        put("quantity", quantity)
        put("selected", selected)
        put("brand", brand)
    }

    private fun JSONObject.toChatAction(): ChatAction =
        ChatAction(
            type = optString("type"),
            label = optString("label"),
            productId = optString("productId").ifBlank { null }
        )

    private fun JSONObject.toCartItem(): CartItem =
        CartItem(
            id = optString("id"),
            productId = optString("productId"),
            productName = optString("productName"),
            productImage = optString("productImage"),
            skuId = optString("skuId").ifBlank { null },
            skuText = optString("skuText"),
            skuPrice = optDouble("skuPrice"),
            quantity = optInt("quantity", 1),
            selected = optBoolean("selected", true),
            brand = optString("brand")
        )

    private fun JSONArray?.toProductList(): List<Product> {
        if (this == null) return emptyList()
        return (0 until length()).mapNotNull { index -> optJSONObject(index)?.toProduct() }
    }

    private fun JSONArray?.toActionList(): List<ChatAction> {
        if (this == null) return emptyList()
        return (0 until length()).mapNotNull { index -> optJSONObject(index)?.toChatAction() }
    }

    private fun JSONArray?.toComparisonColumns(): List<ComparisonColumn> {
        if (this == null) return emptyList()
        return (0 until length()).mapNotNull { index -> optJSONObject(index)?.toComparisonColumn() }
    }

    private fun JSONArray?.toComparisonRows(): List<ComparisonRow> {
        if (this == null) return emptyList()
        return (0 until length()).mapNotNull { index -> optJSONObject(index)?.toComparisonRow() }
    }

    private fun JSONArray?.toComparisonSections(): List<ComparisonSection> {
        if (this == null) return emptyList()
        return (0 until length()).mapNotNull { index -> optJSONObject(index)?.toComparisonSection() }
    }

    private fun JSONArray?.toCartItemList(): List<CartItem> {
        if (this == null) return emptyList()
        return (0 until length()).mapNotNull { index -> optJSONObject(index)?.toCartItem() }
    }

    private fun JSONArray?.toStringList(): List<String> {
        if (this == null) return emptyList()
        return (0 until length()).mapNotNull { index -> optString(index).takeIf { it.isNotBlank() } }
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
