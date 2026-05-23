package com.smartshop.ai.data.model

data class Product(
    val id: String,
    val name: String,
    val description: String,
    val price: Double,
    val originalPrice: Double? = null,
    val imageUrl: String,
    val images: List<String> = emptyList(),
    val category: String,
    val categoryId: String,
    val brand: String,
    val rating: Float,
    val reviewCount: Int,
    val tags: List<String> = emptyList(),
    val specs: Map<String, String> = emptyMap(),
    val faqSummaries: List<String> = emptyList(),
    val reviewSummaries: List<String> = emptyList(),
    val skuSummaries: List<String> = emptyList(),
    val aiComment: String = "",
    val inStock: Boolean = true
) {
    val discount: Int?
        get() = originalPrice?.let { ((1 - price / it) * 100).toInt() }
}
