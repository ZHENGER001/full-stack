package com.smartshop.ai.data.model

data class ProductSku(
    val id: String,
    val productId: String,
    val skuName: String,
    val skuText: String,
    val price: Double,
    val originalPrice: Double? = null,
    val stock: Int
)
