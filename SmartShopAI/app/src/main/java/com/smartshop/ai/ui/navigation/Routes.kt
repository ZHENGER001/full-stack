package com.smartshop.ai.ui.navigation

object Routes {
    const val HOME = "home"
    const val CHAT = "chat"
    const val SEARCH = "search"
    const val PRODUCT_DETAIL = "product/{productId}"
    const val PRODUCT_REVIEWS = "product/{productId}/reviews"
    const val CATEGORY = "category/{categoryId}"

    fun productDetail(productId: String) = "product/$productId"
    fun productReviews(productId: String) = "product/$productId/reviews"
    fun category(categoryId: String) = "category/$categoryId"
}
