package com.smartshop.ai.data.account

import com.smartshop.ai.data.model.FavoriteItem
import com.smartshop.ai.data.model.FootprintItem
import com.smartshop.ai.data.model.Order
import com.smartshop.ai.data.model.OrderItem
import com.smartshop.ai.data.model.ProfileSummary
import com.smartshop.ai.data.model.ShippingAddress
import com.smartshop.ai.data.remote.AddressCreateRequest
import com.smartshop.ai.data.remote.AddressDto
import com.smartshop.ai.data.remote.FavoriteCreateRequest
import com.smartshop.ai.data.remote.FavoriteDto
import com.smartshop.ai.data.remote.FootprintCreateRequest
import com.smartshop.ai.data.remote.FootprintDto
import com.smartshop.ai.data.remote.OrderCreateRequest
import com.smartshop.ai.data.remote.OrderDto
import com.smartshop.ai.data.remote.PaymentRequest
import com.smartshop.ai.data.remote.ProfileSummaryDto
import com.smartshop.ai.data.remote.SmartShopApi
import com.smartshop.ai.data.remote.toProduct
import javax.inject.Inject
import javax.inject.Singleton

@Singleton
class AccountRepository @Inject constructor(
    private val api: SmartShopApi
) {
    suspend fun getSummary(): ProfileSummary = api.getProfileSummary().toProfileSummary()

    suspend fun getFavorites(): List<FavoriteItem> =
        api.getFavorites().items.map { it.toFavoriteItem() }

    suspend fun addFavorite(productId: String): FavoriteItem =
        api.addFavorite(FavoriteCreateRequest(product_id = productId)).toFavoriteItem()

    suspend fun removeFavorite(productId: String): ProfileSummary =
        api.deleteFavorite(productId).toProfileSummary()

    suspend fun getFootprints(): List<FootprintItem> =
        api.getFootprints().items.map { it.toFootprintItem() }

    suspend fun addFootprint(productId: String): FootprintItem =
        api.addFootprint(FootprintCreateRequest(product_id = productId)).toFootprintItem()

    suspend fun getAddresses(): List<ShippingAddress> =
        api.getAddresses().items.map { it.toShippingAddress() }

    suspend fun addAddress(
        receiverName: String,
        phone: String,
        province: String,
        city: String,
        district: String,
        detail: String,
        isDefault: Boolean
    ): ShippingAddress = api.addAddress(
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

    suspend fun getOrders(): List<Order> = api.getOrders().items.map { it.toOrder() }

    suspend fun createOrderFromCart(cartItemIds: List<String>? = null, addressId: String? = null): Order =
        api.createOrder(OrderCreateRequest(cart_item_ids = cartItemIds, address_id = addressId)).toOrder()

    suspend fun createOrderForProduct(productId: String, addressId: String? = null): Order =
        api.createOrder(OrderCreateRequest(product_id = productId, quantity = 1, address_id = addressId)).toOrder()

    suspend fun payOrder(orderId: String, password: String): Order {
        api.payOrder(PaymentRequest(order_id = orderId, password = password))
        return api.getOrders().items.first { it.id == orderId }.toOrder()
    }
}

private fun ProfileSummaryDto.toProfileSummary(): ProfileSummary = ProfileSummary(
    favoriteCount = favorite_count,
    footprintCount = footprint_count,
    orderCount = order_count,
    cartCount = cart_count,
    addressCount = address_count
)

private fun FavoriteDto.toFavoriteItem(): FavoriteItem = FavoriteItem(
    id = id,
    product = product.toProduct(),
    createdAt = created_at
)

private fun FootprintDto.toFootprintItem(): FootprintItem = FootprintItem(
    id = id,
    product = product.toProduct(),
    viewedAt = viewed_at
)

private fun AddressDto.toShippingAddress(): ShippingAddress = ShippingAddress(
    id = id,
    receiverName = receiver_name,
    phone = phone,
    province = province,
    city = city,
    district = district,
    detail = detail,
    isDefault = is_default
)

private fun OrderDto.toOrder(): Order = Order(
    id = id,
    status = status,
    totalAmount = total_amount,
    address = address?.toShippingAddress(),
    items = items.map { item ->
        OrderItem(
            id = item.id,
            productId = item.product_id,
            skuId = item.sku_id,
            title = item.title,
            brand = item.brand,
            imagePath = item.image_path,
            skuName = item.sku_name,
            price = item.price,
            quantity = item.quantity
        )
    }
)
