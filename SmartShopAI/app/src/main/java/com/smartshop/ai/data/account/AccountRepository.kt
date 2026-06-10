package com.smartshop.ai.data.account

import com.smartshop.ai.data.cart.CartRepository
import com.smartshop.ai.data.model.FavoriteItem
import com.smartshop.ai.data.model.FootprintItem
import com.smartshop.ai.data.model.Order
import com.smartshop.ai.data.model.OrderItem
import com.smartshop.ai.data.model.Product
import com.smartshop.ai.data.model.ProductSku
import com.smartshop.ai.data.model.ProfileSummary
import com.smartshop.ai.data.model.ShippingAddress
import com.smartshop.ai.data.payment.MockPaymentPolicy
import com.smartshop.ai.data.product.ProductRepository
import com.smartshop.ai.data.remote.OrderCreateRequest
import com.smartshop.ai.data.remote.OrderDto
import com.smartshop.ai.data.remote.OrderItemDto
import com.smartshop.ai.data.remote.PaymentRequest
import com.smartshop.ai.data.remote.SmartShopApi
import com.smartshop.ai.data.remote.AddressDto
import com.smartshop.ai.data.remote.AddressCreateRequest
import java.util.UUID
import javax.inject.Inject
import javax.inject.Singleton

@Singleton
class AccountRepository @Inject constructor(
    private val productRepository: ProductRepository,
    private val cartRepository: CartRepository,
    private val api: SmartShopApi
) {
    private val favoriteProductIds = linkedSetOf<String>()
    private val footprints = linkedMapOf<String, FootprintItem>()
    private val orders = mutableListOf<Order>()
    private val addresses = mutableListOf(defaultAddress)

    suspend fun getSummary(): ProfileSummary = ProfileSummary(
        favoriteCount = favoriteProductIds.size,
        footprintCount = footprints.size,
        orderCount = orders.size,
        cartCount = cartRepository.getCart().sumOf { it.quantity },
        addressCount = addresses.size
    )

    suspend fun getFavorites(): List<FavoriteItem> =
        favoriteProductIds.mapNotNull { productId ->
            runCatching {
                FavoriteItem(
                    id = "fav_$productId",
                    product = productRepository.getProductDetail(productId),
                    createdAt = nowDate()
                )
            }.getOrNull()
        }

    suspend fun isFavorite(productId: String): Boolean = productId in favoriteProductIds

    suspend fun addFavorite(productId: String): FavoriteItem {
        favoriteProductIds += productId
        return FavoriteItem(
            id = "fav_$productId",
            product = productRepository.getProductDetail(productId),
            createdAt = nowDate()
        )
    }

    suspend fun removeFavorite(productId: String): ProfileSummary {
        favoriteProductIds -= productId
        return getSummary()
    }

    suspend fun getFootprints(): List<FootprintItem> =
        footprints.values.toList().asReversed()

    suspend fun addFootprint(productId: String): FootprintItem {
        val item = FootprintItem(
            id = "footprint_$productId",
            product = productRepository.getProductDetail(productId),
            viewedAt = nowDate()
        )
        footprints[productId] = item
        return item
    }

    suspend fun getAddresses(): List<ShippingAddress> =
        runCatching {
            api.getAddresses().items.map { it.toShippingAddress() }.also { remoteAddresses ->
                addresses.clear()
                addresses += remoteAddresses
            }
        }.getOrElse { addresses.toList() }

    suspend fun addAddress(
        receiverName: String,
        phone: String,
        province: String,
        city: String,
        district: String,
        detail: String,
        isDefault: Boolean
    ): ShippingAddress {
        runCatching {
            api.addAddress(
                AddressCreateRequest(
                    receiver_name = receiverName,
                    phone = phone,
                    province = province,
                    city = city,
                    district = district,
                    detail = detail,
                    is_default = isDefault
                )
            ).toShippingAddress()
        }.onSuccess { remoteAddress ->
            if (remoteAddress.isDefault) {
                addresses.replaceAll { it.copy(isDefault = false) }
            }
            addresses.removeAll { it.id == remoteAddress.id }
            addresses += remoteAddress
            return remoteAddress
        }

        if (isDefault) {
            addresses.replaceAll { it.copy(isDefault = false) }
        }
        val address = ShippingAddress(
            id = "addr_${UUID.randomUUID()}",
            receiverName = receiverName,
            phone = phone,
            province = province,
            city = city,
            district = district,
            detail = detail,
            isDefault = isDefault || addresses.isEmpty()
        )
        addresses += address
        return address
    }

    suspend fun getOrders(): List<Order> =
        runCatching {
            api.getOrders().items.map { it.toOrder() }.also { remoteOrders ->
                orders.clear()
                orders += remoteOrders
            }
        }.getOrElse { orders.toList().asReversed() }

    suspend fun createOrderFromCart(cartItemIds: List<String>? = null, addressId: String? = null): Order {
        runCatching {
            api.createOrder(
                OrderCreateRequest(
                    cart_item_ids = cartItemIds,
                    address_id = addressId
                )
            ).toOrder()
        }.onSuccess { order ->
            orders += order
            return order
        }

        val selected = cartRepository.selectedItems()
            .filter { item -> cartItemIds == null || item.id in cartItemIds }
        require(selected.isNotEmpty()) { "请选择要结算的商品" }
        val orderItems = selected.map { item ->
            OrderItem(
                id = "order_item_${UUID.randomUUID()}",
                productId = item.productId,
                skuId = item.skuId,
                title = item.productName,
                brand = item.brand,
                imagePath = item.productImage,
                skuName = item.skuText,
                price = item.skuPrice,
                quantity = item.quantity
            )
        }
        val amount = orderItems.sumOf { it.price * it.quantity }
        return createOrder(orderItems, amount, addressId)
    }

    suspend fun createOrderForProduct(productId: String, addressId: String? = null): Order {
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
        return createOrderForProduct(product, sku, addressId)
    }

    suspend fun createOrderForProduct(product: Product, sku: ProductSku, addressId: String? = null): Order {
        runCatching {
            api.createOrder(
                OrderCreateRequest(
                    product_id = product.id,
                    sku_id = sku.id,
                    quantity = 1,
                    address_id = addressId
                )
            ).toOrder()
        }.onSuccess { order ->
            orders += order
            return order
        }

        val orderItem = OrderItem(
            id = "order_item_${UUID.randomUUID()}",
            productId = product.id,
            skuId = sku.id,
            title = product.name,
            brand = product.brand,
            imagePath = product.imageUrl,
            skuName = sku.skuText,
            price = sku.price,
            quantity = 1
        )
        return createOrder(listOf(orderItem), sku.price, addressId)
    }

    suspend fun payOrder(orderId: String, password: String): Order {
        require(MockPaymentPolicy.accepts(password)) { "支付密码错误，请输入 123456" }
        runCatching {
            api.payOrder(PaymentRequest(order_id = orderId, password = password))
            api.getOrders().items.firstOrNull { it.id == orderId }?.toOrder()
        }.getOrNull()?.let { paidOrder ->
            val index = orders.indexOfFirst { it.id == orderId }
            if (index >= 0) {
                orders[index] = paidOrder
            } else {
                orders += paidOrder
            }
            return paidOrder
        }

        val index = orders.indexOfFirst { it.id == orderId }
        require(index >= 0) { "订单不存在" }
        val paidOrder = orders[index].copy(status = "paid")
        orders[index] = paidOrder
        return paidOrder
    }

    suspend fun cancelOrder(orderId: String): Order {
        runCatching { api.cancelOrder(orderId).toOrder() }
            .onSuccess { cancelledOrder ->
                val index = orders.indexOfFirst { it.id == orderId }
                if (index >= 0) {
                    orders[index] = cancelledOrder
                } else {
                    orders += cancelledOrder
                }
                return cancelledOrder
            }
        val index = orders.indexOfFirst { it.id == orderId }
        require(index >= 0) { "订单不存在" }
        val cancelledOrder = orders[index].copy(status = "cancelled")
        orders[index] = cancelledOrder
        return cancelledOrder
    }

    private fun createOrder(items: List<OrderItem>, amount: Double, addressId: String?): Order {
        val address = addressId?.let { id -> addresses.firstOrNull { it.id == id } }
            ?: addresses.firstOrNull { it.isDefault }
        val order = Order(
            id = "mock_order_${System.currentTimeMillis()}",
            status = "pending_payment",
            totalAmount = amount,
            address = address,
            items = items,
            userId = "user_001",
            productId = items.firstOrNull()?.productId.orEmpty(),
            skuId = items.firstOrNull()?.skuId,
            productName = items.firstOrNull()?.title.orEmpty(),
            skuText = items.firstOrNull()?.skuName.orEmpty(),
            amount = amount,
            createdAt = nowDate()
        )
        orders += order
        return order
    }

    private fun nowDate(): String = "2026-05-30"

    private fun OrderDto.toOrder(): Order =
        Order(
            id = id,
            status = status,
            totalAmount = total_amount,
            address = address?.toShippingAddress(),
            items = items.map { it.toOrderItem() },
            createdAt = nowDate()
        )

    private fun OrderItemDto.toOrderItem(): OrderItem =
        OrderItem(
            id = id,
            productId = product_id,
            skuId = sku_id,
            title = title,
            brand = brand,
            imagePath = image_path,
            skuName = sku_name,
            price = price,
            quantity = quantity
        )

    private fun AddressDto.toShippingAddress(): ShippingAddress =
        ShippingAddress(
            id = id,
            receiverName = receiver_name,
            phone = phone,
            province = province,
            city = city,
            district = district,
            detail = detail,
            isDefault = is_default
        )

    private companion object {
        val defaultAddress = ShippingAddress(
            id = "addr_default",
            receiverName = "管理员",
            phone = "13800008888",
            province = "上海市",
            city = "上海市",
            district = "浦东新区",
            detail = "SmartShopAI 演示地址",
            isDefault = true
        )
    }
}
