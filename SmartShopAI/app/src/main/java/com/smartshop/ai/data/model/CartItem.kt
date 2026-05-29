package com.smartshop.ai.data.model

data class CartItem(
    val id: String,
    val productId: String,
    val productName: String,
    val productImage: String,
    val skuId: String?,
    val skuText: String,
    val skuPrice: Double,
    val quantity: Int,
    val selected: Boolean,
    val brand: String = ""
) {
    val title: String get() = productName
    val imagePath: String get() = productImage
    val skuName: String get() = skuText
    val price: Double get() = skuPrice
}
