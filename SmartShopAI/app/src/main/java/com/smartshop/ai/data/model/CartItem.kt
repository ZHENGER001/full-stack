package com.smartshop.ai.data.model

data class CartItem(
    val id: String,
    val productId: String,
    val skuId: String?,
    val title: String,
    val brand: String,
    val imagePath: String,
    val skuName: String,
    val price: Double,
    val quantity: Int,
    val selected: Boolean
)
