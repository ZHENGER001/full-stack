package com.smartshop.ai.ui.navigation

import androidx.compose.animation.AnimatedContentTransitionScope
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.Chat
import androidx.compose.material.icons.filled.Home
import androidx.compose.material.icons.filled.Person
import androidx.compose.material.icons.filled.Search
import androidx.compose.material.icons.automirrored.outlined.Chat
import androidx.compose.material.icons.outlined.Home
import androidx.compose.material.icons.outlined.Person
import androidx.compose.material.icons.outlined.Search
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.Icon
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.navigation.NavDestination.Companion.hierarchy
import androidx.navigation.NavGraph.Companion.findStartDestination
import androidx.navigation.NavHostController
import androidx.navigation.NavType
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.currentBackStackEntryAsState
import androidx.navigation.compose.rememberNavController
import androidx.navigation.navArgument
import com.smartshop.ai.ui.camera.CameraScreen
import com.smartshop.ai.ui.camera.ImageResultScreen
import com.smartshop.ai.ui.cart.CartScreen
import com.smartshop.ai.ui.chat.ChatScreen
import com.smartshop.ai.ui.home.HomeScreen
import com.smartshop.ai.ui.auth.LoginScreen
import com.smartshop.ai.ui.auth.SessionViewModel
import com.smartshop.ai.ui.payment.PaymentSuccessScreen
import com.smartshop.ai.ui.product.CategoryProductsScreen
import com.smartshop.ai.ui.product.ProductDetailScreen
import com.smartshop.ai.ui.product.ProductReviewsScreen
import com.smartshop.ai.ui.product.SearchScreen
import com.smartshop.ai.ui.profile.FavoritesScreen
import com.smartshop.ai.ui.profile.FootprintsScreen
import com.smartshop.ai.ui.profile.OrdersScreen
import com.smartshop.ai.ui.profile.AddressesScreen
import com.smartshop.ai.ui.profile.ProfileScreen
import com.smartshop.ai.ui.settings.SettingsScreen
import androidx.hilt.navigation.compose.hiltViewModel

data class BottomNavItem(
    val screen: Screen,
    val label: String,
    val selectedIcon: ImageVector,
    val unselectedIcon: ImageVector
)

val bottomNavItems = listOf(
    BottomNavItem(Screen.Home, "首页", Icons.Filled.Home, Icons.Outlined.Home),
    BottomNavItem(Screen.Chat, "AI导购", Icons.AutoMirrored.Filled.Chat, Icons.AutoMirrored.Outlined.Chat),
    BottomNavItem(Screen.Search, "发现", Icons.Filled.Search, Icons.Outlined.Search),
    BottomNavItem(Screen.Profile, "我的", Icons.Filled.Person, Icons.Outlined.Person),
)

@Composable
fun SmartShopNavHost(
    sessionViewModel: SessionViewModel = hiltViewModel()
) {
    val session by sessionViewModel.session.collectAsState()
    if (!session.isLoaded) {
        Box(modifier = Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
            Text("正在加载...")
        }
        return
    }

    val navController = rememberNavController()
    val navBackStackEntry by navController.currentBackStackEntryAsState()
    val currentDestination = navBackStackEntry?.destination
    val startDestination = if (session.user == null) Screen.Login.route else Screen.Home.route

    val showBottomBar = currentDestination?.route in bottomNavItems.map { it.screen.route }

    Scaffold(
        bottomBar = {
            if (showBottomBar) {
                NavigationBar(
                    containerColor = MaterialTheme.colorScheme.surface,
                    tonalElevation = androidx.compose.ui.unit.Dp(3f)
                ) {
                    bottomNavItems.forEach { item ->
                        val selected = currentDestination?.hierarchy?.any {
                            it.route == item.screen.route
                        } == true
                        NavigationBarItem(
                            icon = {
                                Icon(
                                    imageVector = if (selected) item.selectedIcon else item.unselectedIcon,
                                    contentDescription = item.label
                                )
                            },
                            label = { Text(item.label, style = MaterialTheme.typography.labelSmall) },
                            selected = selected,
                            onClick = {
                                navController.navigate(item.screen.route) {
                                    popUpTo(navController.graph.findStartDestination().id) {
                                        saveState = true
                                    }
                                    launchSingleTop = true
                                    restoreState = true
                                }
                            }
                        )
                    }
                }
            }
        }
    ) { innerPadding ->
        SmartShopNavGraph(
            navController = navController,
            padding = innerPadding,
            startDestination = startDestination
        )
    }
}

@Composable
fun SmartShopNavGraph(
    navController: NavHostController,
    padding: PaddingValues,
    startDestination: String
) {
    val animDuration = 300

    NavHost(
        navController = navController,
        startDestination = startDestination,
        modifier = Modifier.padding(padding),
        enterTransition = {
            fadeIn(animationSpec = tween(animDuration)) + slideIntoContainer(
                towards = AnimatedContentTransitionScope.SlideDirection.Start,
                animationSpec = tween(animDuration)
            )
        },
        exitTransition = {
            fadeOut(animationSpec = tween(animDuration)) + slideOutOfContainer(
                towards = AnimatedContentTransitionScope.SlideDirection.Start,
                animationSpec = tween(animDuration)
            )
        },
        popEnterTransition = {
            fadeIn(animationSpec = tween(animDuration)) + slideIntoContainer(
                towards = AnimatedContentTransitionScope.SlideDirection.End,
                animationSpec = tween(animDuration)
            )
        },
        popExitTransition = {
            fadeOut(animationSpec = tween(animDuration)) + slideOutOfContainer(
                towards = AnimatedContentTransitionScope.SlideDirection.End,
                animationSpec = tween(animDuration)
            )
        }
    ) {
        composable(Screen.Login.route) {
            LoginScreen(
                onLoginSuccess = {
                    navController.navigate(Screen.Home.route) {
                        popUpTo(Screen.Login.route) { inclusive = true }
                        launchSingleTop = true
                    }
                }
            )
        }

        composable(Screen.Home.route) {
            HomeScreen(navController = navController)
        }

        composable(Screen.Chat.route) {
            ChatScreen(navController = navController)
        }

        composable(Screen.Camera.route) {
            CameraScreen(navController = navController)
        }

        composable(Screen.Search.route) {
            SearchScreen(navController = navController)
        }

        composable(Screen.Profile.route) {
            ProfileScreen(navController = navController)
        }

        composable(Screen.Settings.route) {
            SettingsScreen(navController = navController)
        }

        composable(Screen.Favorites.route) {
            FavoritesScreen(navController = navController)
        }

        composable(Screen.Footprints.route) {
            FootprintsScreen(navController = navController)
        }

        composable(Screen.Orders.route) {
            OrdersScreen(navController = navController)
        }

        composable(Screen.Addresses.route) {
            AddressesScreen(navController = navController)
        }

        composable(Screen.Cart.route) {
            CartScreen(navController = navController)
        }

        composable(Screen.ImageResult.route) {
            ImageResultScreen(navController = navController)
        }

        composable(
            route = Screen.ProductDetail.route,
            arguments = listOf(
                navArgument("productId") { type = NavType.StringType }
            )
        ) { backStackEntry ->
            val productId = backStackEntry.arguments?.getString("productId") ?: ""
            ProductDetailScreen(
                productId = productId,
                navController = navController
            )
        }

        composable(
            route = Screen.ProductReviews.route,
            arguments = listOf(
                navArgument("productId") { type = NavType.StringType }
            )
        ) { backStackEntry ->
            val productId = backStackEntry.arguments?.getString("productId") ?: ""
            ProductReviewsScreen(
                productId = productId,
                navController = navController
            )
        }

        composable(
            route = Screen.PaymentSuccess.route,
            arguments = listOf(
                navArgument("amount") { type = NavType.StringType },
                navArgument("productName") { type = NavType.StringType },
                navArgument("skuText") { type = NavType.StringType }
            )
        ) { backStackEntry ->
            val amount = backStackEntry.arguments?.getString("amount")?.toDoubleOrNull() ?: 0.0
            val productName = backStackEntry.arguments?.getString("productName").orEmpty()
            val skuText = backStackEntry.arguments?.getString("skuText").orEmpty()
            PaymentSuccessScreen(
                amount = amount,
                productName = productName,
                skuText = skuText,
                navController = navController
            )
        }

        composable(
            route = Screen.CategoryProducts.route,
            arguments = listOf(
                navArgument("categoryId") { type = NavType.StringType }
            )
        ) { backStackEntry ->
            val categoryId = backStackEntry.arguments?.getString("categoryId") ?: ""
            CategoryProductsScreen(
                categoryId = categoryId,
                navController = navController
            )
        }
    }
}
