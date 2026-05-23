package com.smartshop.ai.data.cart

import com.smartshop.ai.data.model.CartItem
import com.smartshop.ai.data.remote.AddCartItemRequest
import com.smartshop.ai.data.remote.CartDto
import com.smartshop.ai.data.remote.SmartShopApi
import javax.inject.Inject
import javax.inject.Singleton

@Singleton
class CartRepository @Inject constructor(
    private val api: SmartShopApi
) {
    suspend fun getCart(): List<CartItem> =
        api.getCart().toCartItems()

    suspend fun addProduct(productId: String): List<CartItem> =
        api.addCartItem(AddCartItemRequest(product_id = productId)).toCartItems()
}

private fun CartDto.toCartItems(): List<CartItem> = items.map { item ->
    CartItem(
        id = item.id,
        productId = item.product_id,
        skuId = item.sku_id,
        title = item.title,
        brand = item.brand,
        imagePath = item.image_path,
        skuName = item.sku_name,
        price = item.price,
        quantity = item.quantity,
        selected = item.selected
    )
}
