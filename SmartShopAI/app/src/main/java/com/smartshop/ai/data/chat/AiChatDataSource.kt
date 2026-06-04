package com.smartshop.ai.data.chat

import android.content.Context
import android.net.Uri
import com.smartshop.ai.data.remote.ChatStreamRequestDto
import com.smartshop.ai.data.remote.SmartShopApi
import com.smartshop.ai.data.remote.toProduct
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.flow
import kotlinx.coroutines.withContext
import okhttp3.MediaType.Companion.toMediaTypeOrNull
import okhttp3.MultipartBody
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONObject
import javax.inject.Inject

class AiChatDataSource @Inject constructor(
    @ApplicationContext private val context: Context,
    private val api: SmartShopApi
) {

    fun streamAssistantReply(
        text: String,
        imageUri: Uri?
    ): Flow<AiChatEvent> = flow {
        val imageId = imageUri?.let { uploadImage(it) }
        val message = text.ifBlank {
            if (imageId != null) "帮我找类似商品" else text
        }
        val response = api.streamChat(
            ChatStreamRequestDto(
                session_id = "android_default",
                message = message,
                image_id = imageId
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
                        parseEvent(eventName.orEmpty(), dataLines.joinToString("\n"))?.let { emit(it) }
                        eventName = null
                        dataLines.clear()
                    }
                }
            }
        } ?: emit(AiChatEvent.Delta("AI 导购没有返回内容。"))
        emit(AiChatEvent.Done)
    }

    private suspend fun uploadImage(uri: Uri): String = withContext(Dispatchers.IO) {
        val contentType = context.contentResolver.getType(uri)?.toMediaTypeOrNull()
            ?: "image/jpeg".toMediaTypeOrNull()
        val bytes = context.contentResolver.openInputStream(uri)?.use { it.readBytes() }
            ?: error("无法读取图片")
        val body = bytes.toRequestBody(contentType)
        val part = MultipartBody.Part.createFormData("file", "chat_image.jpg", body)
        api.uploadAgentImage(part).image_id
    }

    private fun parseEvent(event: String, data: String): AiChatEvent? {
        val json = JSONObject(data)
        return when (event) {
            "delta" -> AiChatEvent.Delta(json.optString("text"))
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
                        reason = item.optString("reason").ifBlank { null }
                    ).toProduct()
                }
                AiChatEvent.Products(products)
            }
            "actions" -> {
                val actionsJson = json.optJSONArray("actions") ?: return null
                val actions = (0 until actionsJson.length()).map { index ->
                    val item = actionsJson.getJSONObject(index)
                    when (item.optString("type")) {
                        "add_to_cart" -> "加入购物车:${item.optString("product_id")}"
                        "go_detail" -> "查看详情:${item.optString("product_id")}"
                        else -> item.toString()
                    }
                }
                AiChatEvent.Actions(actions)
            }
            "done" -> AiChatEvent.Done
            else -> null
        }
    }
}
