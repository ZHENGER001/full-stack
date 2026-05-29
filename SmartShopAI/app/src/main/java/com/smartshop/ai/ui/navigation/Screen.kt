package com.smartshop.ai.ui.navigation

import android.net.Uri

sealed class Screen(val route: String) {
    object Login : Screen("login")
    object Home : Screen("home")
    object Chat : Screen("chat")
    object Camera : Screen("camera")
    object Profile : Screen("profile")
    object Settings : Screen("settings")
    object Search : Screen("search")
    object ProductDetail : Screen("product/{productId}") {
        fun createRoute(productId: String) = "product/$productId"
    }
    object ProductReviews : Screen("product/{productId}/reviews") {
        fun createRoute(productId: String) = "product/$productId/reviews"
    }
    object PaymentSuccess : Screen("payment_success/{amount}/{productName}/{skuText}") {
        fun createRoute(amount: Double, productName: String, skuText: String): String =
            "payment_success/${"%.2f".format(amount)}/${Uri.encode(productName)}/${Uri.encode(skuText)}"
    }
    object CategoryProducts : Screen("category/{categoryId}") {
        fun createRoute(categoryId: String) = "category/$categoryId"
    }
    object ImageResult : Screen("image_result")
    object Favorites : Screen("favorites")
    object Footprints : Screen("footprints")
    object Orders : Screen("orders")
    object Addresses : Screen("addresses")
    object Cart : Screen("cart")
}
