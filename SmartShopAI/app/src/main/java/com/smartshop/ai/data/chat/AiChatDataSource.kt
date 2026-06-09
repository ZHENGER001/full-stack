package com.smartshop.ai.data.chat

import android.content.Context
import android.net.Uri
import com.smartshop.ai.data.model.ChatAction
import com.smartshop.ai.data.model.CartItem
import com.smartshop.ai.data.model.ComparisonColumn
import com.smartshop.ai.data.model.ComparisonContent
import com.smartshop.ai.data.model.ComparisonRow
import com.smartshop.ai.data.model.ComparisonSection
import com.smartshop.ai.data.remote.CartItemDto
import com.smartshop.ai.data.remote.ChatStreamRequestDto
import com.smartshop.ai.data.remote.SmartShopApi
import com.smartshop.ai.data.remote.toCartItem
import com.smartshop.ai.data.remote.toProduct
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.catch
import kotlinx.coroutines.flow.flow
import kotlinx.coroutines.flow.flowOn
import kotlinx.coroutines.withContext
import okhttp3.MediaType.Companion.toMediaTypeOrNull
import okhttp3.MultipartBody
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONArray
import org.json.JSONObject
import java.util.UUID
import javax.inject.Inject

class AiChatDataSource @Inject constructor(
    @ApplicationContext private val context: Context,
    private val api: SmartShopApi,
    private val imageUnderstandingRepository: ImageUnderstandingRepository
) {

    fun streamAssistantReply(
        text: String,
        imageUri: Uri?,
        cartContext: List<CartItem> = emptyList()
    ): Flow<AiChatEvent> = flow {
        var receivedDone = false
        val imageHint = imageUri?.let { imageUnderstandingRepository.describeImage(it) }.orEmpty()
        val imageId = imageUri?.let { uploadImage(it) }
        val baseMessage = text.ifBlank {
            if (imageId != null) "帮我找类似商品" else text
        }
        val message = listOf(baseMessage, imageHint)
            .map { it.trim() }
            .filter { it.isNotBlank() }
            .joinToString(" ")
        val response = api.streamChat(
            ChatStreamRequestDto(
                session_id = stableSessionId(),
                message = message,
                image_id = imageId,
                cart_context = cartContext.map { it.toAgentCartContext() }
            )
        )
        if (!response.isSuccessful) {
            emit(AiChatEvent.Delta("AI 导购服务暂时不可用，请稍后重试。"))
            emit(AiChatEvent.Done)
            return@flow
        }
        response.body()?.charStream()?.buffered()?.use { reader ->
            var eventName: String? = null
            val dataLines = mutableListOf<String>()
            for (line in reader.lineSequence()) {
                when {
                    line.startsWith("event:") -> eventName = line.removePrefix("event:").trim()
                    line.startsWith("data:") -> dataLines += line.removePrefix("data:").trim()
                    line.isBlank() && eventName != null -> {
                        parseEvent(eventName.orEmpty(), dataLines.joinToString("\n"))?.let { event ->
                            if (event is AiChatEvent.Done) {
                                receivedDone = true
                            }
                            emit(event)
                        }
                        eventName = null
                        dataLines.clear()
                    }
                }
            }
        } ?: emit(AiChatEvent.Delta("AI 导购没有返回内容。"))
        if (!receivedDone) {
            emit(AiChatEvent.Done)
        }
    }.catch {
        emit(AiChatEvent.Delta("AI 导购服务暂时不可用，请稍后重试。"))
        emit(AiChatEvent.Done)
    }.flowOn(Dispatchers.IO)

    private suspend fun uploadImage(uri: Uri): String = withContext(Dispatchers.IO) {
        val contentType = context.contentResolver.getType(uri)?.toMediaTypeOrNull()
            ?: "image/jpeg".toMediaTypeOrNull()
        val bytes = context.contentResolver.openInputStream(uri)?.use { it.readBytes() }
            ?: error("无法读取图片")
        val body = bytes.toRequestBody(contentType)
        val part = MultipartBody.Part.createFormData("file", "chat_image.jpg", body)
        api.uploadAgentImage(part).image_id
    }

    suspend fun transcribeAudio(uri: Uri): String? = withContext(Dispatchers.IO) {
        val contentType = context.contentResolver.getType(uri)?.toMediaTypeOrNull()
            ?: uri.fallbackAudioMediaType()
        val bytes = context.contentResolver.openInputStream(uri)?.use { it.readBytes() }
            ?: error("无法读取录音")
        val body = bytes.toRequestBody(contentType)
        val part = MultipartBody.Part.createFormData("file", "voice_input.${uri.audioFileExtension()}", body)
        api.transcribeAgentAudio(part)
            .takeIf { it.available }
            ?.text
            ?.trim()
            ?.takeIf { it.isNotBlank() }
    }

    private fun parseEvent(event: String, data: String): AiChatEvent? {
        val json = JSONObject(data)
        return when (event) {
            "delta" -> AiChatEvent.Delta(json.optString("text"))
            "answer" -> AiChatEvent.Delta(json.optString("text").ifBlank { json.optString("answer") })
            "error" -> AiChatEvent.Delta(json.optString("message").ifBlank { "AI 导购暂时遇到问题，请稍后再试。" })
            "products" -> {
                val productsJson = json.optJSONArray("products") ?: return null
                val products = (0 until productsJson.length()).map { index ->
                    val item = productsJson.getJSONObject(index)
                    com.smartshop.ai.data.remote.ProductCardDto(
                        id = item.getString("id"),
                        title = item.getString("title"),
                        brand = item.getString("brand"),
                        category = item.optString("category"),
                        subcategory = item.optString("subcategory"),
                        price = item.getDouble("price"),
                        rating = item.optDouble("rating", 0.0).toFloat(),
                        image_path = item.optString("image_path"),
                        reason = item.optString("reason").ifBlank { null },
                        marketing_description = item.optString("marketing_description").ifBlank { null },
                        review_count = item.optInt("review_count", 0),
                        sku_count = item.optInt("sku_count", 0),
                        faq_count = item.optInt("faq_count", 0),
                        stock = item.optInt("stock", 0),
                        sku_summary = item.optString("sku_summary").ifBlank { null }
                    ).toProduct()
                }
                AiChatEvent.Products(products)
            }
            "alternatives" -> {
                val productsJson = json.optJSONArray("products") ?: return null
                val products = (0 until productsJson.length()).map { index ->
                    val item = productsJson.getJSONObject(index)
                    com.smartshop.ai.data.remote.ProductCardDto(
                        id = item.getString("id"),
                        title = item.getString("title"),
                        brand = item.getString("brand"),
                        category = item.optString("category"),
                        subcategory = item.optString("subcategory"),
                        price = item.getDouble("price"),
                        rating = item.optDouble("rating", 0.0).toFloat(),
                        image_path = item.optString("image_path"),
                        reason = item.optString("reason").ifBlank { null },
                        marketing_description = item.optString("marketing_description").ifBlank { null },
                        review_count = item.optInt("review_count", 0),
                        sku_count = item.optInt("sku_count", 0),
                        faq_count = item.optInt("faq_count", 0),
                        stock = item.optInt("stock", 0),
                        sku_summary = item.optString("sku_summary").ifBlank { null }
                    ).toProduct()
                }
                AiChatEvent.Alternatives(products)
            }
            "comparison" -> AiChatEvent.Comparison(json.toComparisonContent())
            "actions" -> {
                val actionsJson = json.optJSONArray("actions") ?: return null
                val actions = (0 until actionsJson.length()).mapNotNull { index ->
                    parseAction(actionsJson.get(index))
                }
                AiChatEvent.Actions(actions)
            }
            "cart" -> {
                val itemsJson = json.optJSONArray("items") ?: return null
                val items = (0 until itemsJson.length()).map { index ->
                    val item = itemsJson.getJSONObject(index)
                    CartItemDto(
                        id = item.getString("id"),
                        product_id = item.getString("product_id"),
                        sku_id = item.optString("sku_id").ifBlank { null },
                        title = item.getString("title"),
                        brand = item.getString("brand"),
                        image_path = item.optString("image_path"),
                        sku_name = item.optString("sku_name").ifBlank { "默认规格" },
                        price = item.optDouble("price", 0.0),
                        quantity = item.optInt("quantity", 1),
                        selected = item.optBoolean("selected", true)
                    ).toCartItem()
                }
                AiChatEvent.Cart(items = items, totalAmount = json.optDouble("total_amount", 0.0))
            }
            "order_status" -> AiChatEvent.OrderStatus(
                status = json.optString("status"),
                message = json.optString("message").ifBlank { defaultOrderStatusMessage(json.optString("status")) },
                orderId = json.optString("order_id").ifBlank { null },
                paymentId = json.optString("payment_id").ifBlank { null }
            )
            "done" -> AiChatEvent.Done
            else -> null
        }
    }

    private fun JSONObject.optNullableString(key: String): String? {
        if (!has(key) || isNull(key)) return null
        val value = optString(key).trim()
        return value.takeIf { it.isNotBlank() && !it.equals("null", ignoreCase = true) }
    }

    private fun JSONObject.toComparisonContent(): ComparisonContent =
        ComparisonContent(
            title = optString("title"),
            summary = optString("summary"),
            columns = optJSONArray("columns").toComparisonColumns(),
            rows = optJSONArray("rows").toComparisonRows(),
            sections = optJSONArray("sections").toComparisonSections(),
            recommendation = optString("recommendation"),
            footnote = optNullableString("footnote")
        )

    private fun JSONArray?.toComparisonColumns(): List<ComparisonColumn> {
        if (this == null) return emptyList()
        return (0 until length()).mapNotNull { index ->
            optJSONObject(index)?.let { item ->
                ComparisonColumn(
                    label = item.optString("label"),
                    productId = item.optNullableString("product_id") ?: item.optNullableString("productId")
                )
            }
        }
    }

    private fun JSONArray?.toComparisonRows(): List<ComparisonRow> {
        if (this == null) return emptyList()
        return (0 until length()).mapNotNull { index ->
            optJSONObject(index)?.let { item ->
                ComparisonRow(
                    dimension = item.optString("dimension"),
                    values = item.optJSONArray("values").toStringList(),
                    highlightIndex = when {
                        item.has("highlight_index") && !item.isNull("highlight_index") -> item.optInt("highlight_index")
                        item.has("highlightIndex") && !item.isNull("highlightIndex") -> item.optInt("highlightIndex")
                        else -> null
                    }
                )
            }
        }
    }

    private fun JSONArray?.toComparisonSections(): List<ComparisonSection> {
        if (this == null) return emptyList()
        return (0 until length()).mapNotNull { index ->
            optJSONObject(index)?.let { item ->
                ComparisonSection(
                    title = item.optString("title"),
                    productId = item.optNullableString("product_id") ?: item.optNullableString("productId"),
                    bullets = item.optJSONArray("bullets").toStringList()
                )
            }
        }
    }

    private fun JSONArray?.toStringList(): List<String> {
        if (this == null) return emptyList()
        return (0 until length()).mapNotNull { index ->
            optString(index).trim().takeIf { it.isNotBlank() }
        }
    }

    private fun parseAction(raw: Any): ChatAction? {
        if (raw is String) {
            return parseLegacyAction(raw)
        }
        if (raw !is JSONObject) {
            return null
        }
        val type = raw.optString("type")
        if (type !in allowedActionTypes) {
            return null
        }
        val productId = raw.optString("product_id").ifBlank {
            raw.optString("productId")
        }.ifBlank { null }
        val label = raw.optString("label").ifBlank { defaultActionLabel(type) }
        return ChatAction(type = type, label = label, productId = productId)
    }

    private fun parseLegacyAction(action: String): ChatAction? {
        return when {
            action.startsWith("加入购物车:") -> ChatAction(
                type = "add_to_cart",
                label = "加入购物车",
                productId = action.substringAfter(":").ifBlank { null }
            )
            action.startsWith("查看详情:") -> ChatAction(
                type = "go_detail",
                label = "查看详情",
                productId = action.substringAfter(":").ifBlank { null }
            )
            else -> ChatAction(type = "search_more", label = action)
        }
    }

    private fun stableSessionId(): String {
        val prefs = context.getSharedPreferences("smartshop_ai_chat", Context.MODE_PRIVATE)
        val existing = prefs.getString(KEY_SESSION_ID, null)
        if (!existing.isNullOrBlank()) {
            return existing
        }
        val created = "android_${UUID.randomUUID()}"
        prefs.edit().putString(KEY_SESSION_ID, created).apply()
        return created
    }

    private fun defaultActionLabel(type: String): String =
        when (type) {
            "go_detail" -> "查看详情"
            "add_to_cart" -> "加入购物车"
            "open_cart" -> "打开购物车"
            "search_more" -> "查看更多"
            else -> "执行"
        }

    private fun defaultOrderStatusMessage(status: String): String =
        when (status) {
            "checking_cart" -> "正在读取购物车"
            "need_address" -> "等待补充收货地址"
            "awaiting_confirmation" -> "等待确认下单"
            "creating_order" -> "正在创建订单"
            "paying" -> "正在模拟支付"
            "paid" -> "支付成功"
            "failed" -> "下单失败"
            "cancelled" -> "已取消下单"
            else -> "订单状态更新"
        }

    private fun CartItem.toAgentCartContext(): Map<String, Any> =
        buildMap {
            put("id", id)
            put("product_id", productId)
            put("productId", productId)
            skuId?.let { put("sku_id", it) }
            put("title", productName)
            put("sku_name", skuText)
            put("quantity", quantity)
            put("selected", selected)
        }

    private fun Uri.audioFileExtension(): String =
        lastPathSegment
            ?.substringAfterLast('.', missingDelimiterValue = "")
            ?.lowercase()
            ?.takeIf { it.isNotBlank() }
            ?: "aac"

    private fun Uri.fallbackAudioMediaType() =
        when (audioFileExtension()) {
            "aac" -> "audio/aac"
            "mp3" -> "audio/mpeg"
            "wav" -> "audio/wav"
            "amr" -> "audio/amr"
            "3gp", "3gpp" -> "audio/3gpp"
            else -> "audio/aac"
        }.toMediaTypeOrNull()

    private companion object {
        const val KEY_SESSION_ID = "agent_session_id"
        val allowedActionTypes = setOf("go_detail", "add_to_cart", "open_cart", "search_more")
    }
}
