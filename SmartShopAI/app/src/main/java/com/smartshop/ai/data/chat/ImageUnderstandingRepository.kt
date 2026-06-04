package com.smartshop.ai.data.chat

import android.content.Context
import android.net.Uri
import com.google.mlkit.vision.common.InputImage
import com.google.mlkit.vision.label.ImageLabeling
import com.google.mlkit.vision.label.defaults.ImageLabelerOptions
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlin.coroutines.resume
import kotlinx.coroutines.suspendCancellableCoroutine
import javax.inject.Inject
import javax.inject.Singleton

@Singleton
class ImageUnderstandingRepository @Inject constructor(
    @ApplicationContext private val context: Context
) {
    suspend fun describeImage(uri: Uri): String =
        suspendCancellableCoroutine { continuation ->
            val image = runCatching { InputImage.fromFilePath(context, uri) }.getOrElse {
                continuation.resume("")
                return@suspendCancellableCoroutine
            }
            ImageLabeling.getClient(ImageLabelerOptions.DEFAULT_OPTIONS)
                .process(image)
                .addOnSuccessListener { labels ->
                    val labelText = labels
                        .filter { it.confidence >= MIN_CONFIDENCE }
                        .sortedByDescending { it.confidence }
                        .take(MAX_LABELS)
                        .joinToString(" ") { it.text }
                    val mappedTerms = mapLabelsToSearchTerms(labelText)
                    continuation.resume(
                        when {
                            labelText.isBlank() && mappedTerms.isBlank() -> ""
                            mappedTerms.isBlank() -> "图片识别标签：$labelText"
                            else -> "图片识别标签：$labelText 推断品类：$mappedTerms"
                        }
                    )
                }
                .addOnFailureListener {
                    continuation.resume("")
                }
        }

    private fun mapLabelsToSearchTerms(labelText: String): String {
        val lower = labelText.lowercase()
        val terms = linkedSetOf<String>()
        if (containsAny(lower, "headphone", "earbud", "audio", "speaker")) {
            terms += "耳机 蓝牙 通勤"
        }
        if (containsAny(lower, "shoe", "footwear", "sneaker", "running")) {
            terms += "鞋 运动 跑步"
        }
        if (containsAny(lower, "clothing", "shirt", "jacket", "coat", "hoodie")) {
            terms += "衣服 卫衣 外套"
        }
        if (containsAny(lower, "bag", "backpack", "handbag")) {
            terms += "包 背包 通勤"
        }
        if (containsAny(lower, "phone", "mobile", "tablet", "laptop", "computer")) {
            terms += "数码电子 手机 平板 笔记本"
        }
        if (containsAny(lower, "keyboard", "mouse", "desk", "stationery", "office")) {
            terms += "办公用品 键盘 鼠标"
        }
        if (containsAny(lower, "cosmetic", "skin", "cream", "lotion", "beauty")) {
            terms += "美妆护肤 洁面 防晒"
        }
        if (containsAny(lower, "food", "snack", "coffee", "drink", "beverage")) {
            terms += "食品饮料 零食 咖啡"
        }
        return terms.joinToString(" ")
    }

    private fun containsAny(text: String, vararg needles: String): Boolean =
        needles.any { it in text }

    private companion object {
        const val MIN_CONFIDENCE = 0.45f
        const val MAX_LABELS = 5
    }
}
