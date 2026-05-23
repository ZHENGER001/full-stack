package com.smartshop.ai.data.remote

import android.net.Uri
import com.smartshop.ai.BuildConfig
import com.smartshop.ai.data.model.Category
import com.smartshop.ai.data.model.Product

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
    aiComment = reason.orEmpty()
)

fun ProductDetailDto.toProduct(): Product = Product(
    id = id,
    name = title,
    description = marketing_description,
    price = price,
    originalPrice = null,
    imageUrl = image_path.toAssetUrl(),
    category = category,
    categoryId = category,
    brand = brand,
    rating = rating,
    reviewCount = user_reviews.size,
    specs = skus.firstOrNull()?.properties.orEmpty(),
    faqSummaries = official_faq.map { "${it.question}\n${it.answer}" },
    reviewSummaries = user_reviews.map { "${it.nickname}：${it.content}" },
    skuSummaries = skus.map { "${it.sku_name} ¥${"%.0f".format(it.price)} 库存${it.stock}" },
    aiComment = marketing_description,
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

private fun String.toAssetUrl(): String {
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
