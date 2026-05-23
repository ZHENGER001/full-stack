package com.smartshop.ai.ui.navigation

sealed class Screen(val route: String) {
    object Home : Screen("home")
    object Chat : Screen("chat")
    object Camera : Screen("camera")
    object Profile : Screen("profile")
    object Settings : Screen("settings")
    object Search : Screen("search")
    object ProductDetail : Screen("product/{productId}") {
        fun createRoute(productId: String) = "product/$productId"
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
