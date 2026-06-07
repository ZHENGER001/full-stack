package com.smartshop.ai.data.cart

import com.smartshop.ai.data.model.CartItem
import com.smartshop.ai.data.model.Product
import com.smartshop.ai.data.model.ProductSku
import com.smartshop.ai.data.product.ProductRepository
import com.smartshop.ai.data.remote.AddCartItemRequest
import com.smartshop.ai.data.remote.SmartShopApi
import com.smartshop.ai.data.remote.toCartItem
import javax.inject.Inject
import javax.inject.Singleton

@Singleton
class CartRepository @Inject constructor(
    private val productRepository: ProductRepository,
    private val api: SmartShopApi
) {
    private val cartItems = linkedMapOf<String, CartItem>()

    suspend fun getCart(): List<CartItem> =
        runCatching { syncRemoteCart { api.getCart().items.map { it.toCartItem() } } }
            .getOrElse { cartItems.values.toList() }

    suspend fun addProduct(productId: String): List<CartItem> =
        runCatching {
            syncRemoteCart {
                api.addCartItem(AddCartItemRequest(product_id = productId)).items.map { it.toCartItem() }
            }
        }.getOrElse {
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
            addProductLocal(product = product, sku = sku)
        }

    suspend fun addProduct(product: Product, sku: ProductSku, quantity: Int = 1): List<CartItem> =
        runCatching {
            syncRemoteCart {
                api.addCartItem(
                    AddCartItemRequest(
                        product_id = product.id,
                        sku_id = sku.id,
                        quantity = quantity
                    )
                ).items.map { it.toCartItem() }
            }
        }.getOrElse {
            addProductLocal(product = product, sku = sku, quantity = quantity)
        }

    suspend fun clear(): List<CartItem> =
        runCatching { syncRemoteCart { api.clearCart().items.map { it.toCartItem() } } }
            .getOrElse {
                cartItems.clear()
                emptyList()
            }

    suspend fun selectedItems(): List<CartItem> =
        getCart().filter { it.selected }

    private suspend fun syncRemoteCart(load: suspend () -> List<CartItem>): List<CartItem> {
        val items = load()
        cartItems.clear()
        items.forEach { item -> cartItems[item.id] = item }
        return items
    }

    private fun addProductLocal(product: Product, sku: ProductSku, quantity: Int = 1): List<CartItem> {
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
            current.copy(quantity = current.quantity + quantity, selected = true)
        }
        return cartItems.values.toList()
    }
}
