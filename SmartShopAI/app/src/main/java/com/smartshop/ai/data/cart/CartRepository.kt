package com.smartshop.ai.data.cart

import com.smartshop.ai.data.model.CartItem
import com.smartshop.ai.data.model.Product
import com.smartshop.ai.data.model.ProductSku
import com.smartshop.ai.data.product.ProductRepository
import javax.inject.Inject
import javax.inject.Singleton

@Singleton
class CartRepository @Inject constructor(
    private val productRepository: ProductRepository
) {
    private val cartItems = linkedMapOf<String, CartItem>()

    suspend fun getCart(): List<CartItem> = cartItems.values.toList()

    suspend fun addProduct(productId: String): List<CartItem> {
        val product = productRepository.getProductDetail(productId)
        val sku = product.skus.firstOrNull { it.stock > 0 }
            ?: ProductSku(
                id = "${product.id}_default",
                productId = product.id,
                skuName = "默认规格",
                skuText = "默认规格",
                price = product.price,
                originalPrice = product.originalPrice,
                stock = 1
            )
        return addProduct(product = product, sku = sku)
    }

    fun addProduct(product: Product, sku: ProductSku, quantity: Int = 1): List<CartItem> {
        val itemId = "${product.id}_${sku.id}"
        val current = cartItems[itemId]
        cartItems[itemId] = if (current == null) {
            CartItem(
                id = itemId,
                productId = product.id,
                productName = product.name,
                productImage = product.imageUrl,
                skuId = sku.id,
                skuText = sku.skuText,
                skuPrice = sku.price,
                quantity = quantity,
                selected = true,
                brand = product.brand
            )
        } else {
            current.copy(quantity = current.quantity + quantity)
        }
        return cartItems.values.toList()
    }

    fun selectedItems(): List<CartItem> =
        cartItems.values.filter { it.selected }
}
