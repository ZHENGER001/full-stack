package com.smartshop.ai.data.remote

import android.net.Uri
import com.smartshop.ai.BuildConfig
import com.smartshop.ai.data.model.CartItem
import com.smartshop.ai.data.model.Category
import com.smartshop.ai.data.model.Product
import com.smartshop.ai.data.model.ProductReview
import com.smartshop.ai.data.model.ProductSku

fun ProductCardDto.toProduct(): Product = Product(
    id = id,
    name = title,
    description = marketing_description.orEmpty(),
    price = price,
    originalPrice = null,
    imageUrl = image_path.toAssetUrl(),
    category = category.orEmpty(),
    categoryId = category.orEmpty(),
    brand = brand,
    rating = rating,
    reviewCount = review_count,
    tags = listOfNotNull(category, subcategory).filter { it.isNotBlank() },
    specs = mapOf(
        "SKU" to "${sku_count} 个",
        "FAQ" to "${faq_count} 条",
        "库存" to stock.toString()
    ),
    skuSummaries = sku_summary?.takeIf { it.isNotBlank() }?.let { listOf(it) }.orEmpty(),
    faqSummaries = faq_summary,
    reviewSummaries = review_summary,
    aiComment = userFacingComment(reason, marketing_description),
    recommendationTitle = recommendation_title.orEmpty()
)

fun ProductDetailDto.toProduct(): Product = Product(
    id = id,
    name = title,
    description = marketing_description.take(130),
    price = price,
    originalPrice = null,
    imageUrl = image_path.toAssetUrl(),
    category = category,
    categoryId = category,
    brand = brand,
    rating = rating,
    reviewCount = user_reviews.size,
    specs = skus.firstOrNull()?.properties.orEmpty(),
    skus = skus.map { sku ->
        val skuText = sku.properties.entries.joinToString(" / ") { "${it.key}: ${it.value}" }
            .ifBlank { sku.sku_name }
        ProductSku(
            id = sku.sku_id,
            productId = id,
            skuName = sku.sku_name,
            skuText = skuText,
            price = sku.price,
            originalPrice = null,
            stock = sku.stock
        )
    },
    reviews = user_reviews.mapIndexed { index, review ->
        ProductReview(
            id = "${id}_review_${index + 1}",
            productId = id,
            userId = "api_user_${index + 1}",
            userName = review.nickname,
            userAvatar = "",
            rating = review.rating,
            content = review.content,
            skuText = skus.takeIf { it.isNotEmpty() }
                ?.get(index % skus.size)
                ?.sku_name
                ?: "默认规格",
            createdAt = "2026-05-${(20 + index).toString().padStart(2, '0')}"
        )
    },
    faqSummaries = official_faq.map { "${it.question}\n${it.answer}" },
    reviewSummaries = user_reviews.map { "${it.nickname}：${it.content}" },
    skuSummaries = skus.map { "${it.sku_name} ¥${"%.0f".format(it.price)} 库存${it.stock}" },
    aiComment = marketing_description.take(120),
    inStock = skus.any { it.stock > 0 }
)

fun CategoryDto.toCategory(index: Int): Category = Category(
    id = name,
    name = name,
    icon = listOf("美", "数", "衣", "食").getOrElse(index) { "品" },
    subcategories = subcategories.map { subcategory ->
        Category(id = subcategory, name = subcategory, icon = "")
    }
)

fun CartItemDto.toCartItem(): CartItem = CartItem(
    id = id,
    productId = product_id,
    productName = title,
    productImage = image_path.toAssetUrl(),
    skuId = sku_id,
    skuText = sku_name,
    skuPrice = price,
    quantity = quantity,
    selected = selected,
    brand = brand
)

fun String.toSmartShopAssetUrl(): String {
    if (startsWith("http://") || startsWith("https://")) return this
    val base = BuildConfig.SMARTSHOP_BASE_URL.trimEnd('/')
    val normalized = replace("\\", "/").trimStart('/')
    if (startsWith("/api/") || normalized.startsWith("api/")) return "$base/$normalized"
    if (normalized.startsWith("uploads/")) return "$base/$normalized"
    if (normalized.startsWith("assets/")) return "$base/$normalized"
    val encodedPath = normalized
        .split("/")
        .joinToString("/") { segment -> Uri.encode(segment) }
    return "$base/assets/$encodedPath"
}

private fun String.toAssetUrl(): String = toSmartShopAssetUrl()

private fun userFacingComment(reason: String?, marketingDescription: String?): String {
    val candidate = reason
        ?.takeIf { it.isNotBlank() && !it.trim().equals("null", ignoreCase = true) }
        ?.takeUnless { it.contains("RRF", ignoreCase = true) }
        ?.takeUnless { it.contains("retrieval", ignoreCase = true) }
        ?.takeUnless { it.contains("Matched by", ignoreCase = true) }
    return candidate ?: marketingDescription.orEmpty()
}
