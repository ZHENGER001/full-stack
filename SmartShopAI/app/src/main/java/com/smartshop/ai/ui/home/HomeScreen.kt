package com.smartshop.ai.ui.home

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.grid.GridCells
import androidx.compose.foundation.lazy.grid.GridItemSpan
import androidx.compose.foundation.lazy.grid.LazyVerticalGrid
import androidx.compose.foundation.lazy.grid.items
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowForward
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.navigation.NavHostController
import com.smartshop.ai.data.mock.MockData
import com.smartshop.ai.data.model.Banner
import com.smartshop.ai.data.model.Category
import com.smartshop.ai.data.model.Product
import com.smartshop.ai.ui.components.BannerCarousel
import com.smartshop.ai.ui.components.CategoryChip
import com.smartshop.ai.ui.components.ProductCard
import com.smartshop.ai.ui.components.ShimmerProductGrid
import com.smartshop.ai.ui.components.SmartShopSearchBar
import com.smartshop.ai.ui.navigation.Screen
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

// ==================== ViewModel ====================

data class HomeUiState(
    val products: List<Product> = emptyList(),
    val categories: List<Category> = emptyList(),
    val banners: List<Banner> = emptyList(),
    val isLoading: Boolean = false,
    val selectedCategory: String? = null
)

class HomeViewModel : ViewModel() {

    private val _uiState = MutableStateFlow(HomeUiState(isLoading = true))
    val uiState: StateFlow<HomeUiState> = _uiState.asStateFlow()

    init {
        loadData()
    }

    private fun loadData() {
        _uiState.value = HomeUiState(
            products = MockData.getHotProducts(10),
            categories = MockData.categories,
            banners = MockData.banners,
            isLoading = false,
            selectedCategory = null
        )
    }

    fun selectCategory(categoryId: String?) {
        val currentState = _uiState.value
        val newSelectedId = if (currentState.selectedCategory == categoryId) null else categoryId
        val filteredProducts = if (newSelectedId == null) {
            MockData.getHotProducts(10)
        } else {
            MockData.getProductsByCategory(newSelectedId)
        }
        _uiState.value = currentState.copy(
            selectedCategory = newSelectedId,
            products = filteredProducts
        )
    }
}

// ==================== Screen ====================

@Composable
fun HomeScreen(
    navController: NavHostController,
    viewModel: HomeViewModel = viewModel()
) {
    val uiState by viewModel.uiState.collectAsState()

    if (uiState.isLoading) {
        Column(modifier = Modifier.fillMaxSize().padding(top = 120.dp)) {
            ShimmerProductGrid()
        }
        return
    }

    LazyVerticalGrid(
        columns = GridCells.Fixed(2),
        modifier = Modifier.fillMaxSize(),
        contentPadding = PaddingValues(bottom = 80.dp),
        horizontalArrangement = Arrangement.spacedBy(12.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp)
    ) {
        // Greeting + Search bar (full span)
        item(span = { GridItemSpan(2) }) {
            Column(modifier = Modifier.padding(horizontal = 16.dp, vertical = 12.dp)) {
                Text(
                    text = "你好！今天想买点什么？",
                    style = MaterialTheme.typography.headlineSmall,
                    fontWeight = FontWeight.Bold,
                    color = MaterialTheme.colorScheme.onBackground
                )
                Spacer(modifier = Modifier.height(12.dp))
                SmartShopSearchBar(
                    query = "",
                    onQueryChange = {},
                    onSearch = {},
                    enabled = false,
                    placeholder = "搜索商品、品牌、品类...",
                    modifier = Modifier.clickable {
                        navController.navigate(Screen.Search.route)
                    }
                )
            }
        }

        // Banner carousel (full span)
        item(span = { GridItemSpan(2) }) {
            BannerCarousel(
                banners = uiState.banners,
                modifier = Modifier.padding(vertical = 4.dp),
                onBannerClick = {}
            )
        }

        // Category row (full span)
        item(span = { GridItemSpan(2) }) {
            LazyRow(
                contentPadding = PaddingValues(horizontal = 16.dp),
                horizontalArrangement = Arrangement.spacedBy(8.dp),
                modifier = Modifier.padding(vertical = 8.dp)
            ) {
                items(uiState.categories, key = { it.id }) { category ->
                    CategoryChip(
                        category = category,
                        selected = uiState.selectedCategory == category.id,
                        onClick = { viewModel.selectCategory(category.id) }
                    )
                }
            }
        }

        // Section header (full span)
        item(span = { GridItemSpan(2) }) {
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(horizontal = 16.dp, vertical = 4.dp),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically
            ) {
                Text(
                    text = "热门推荐",
                    style = MaterialTheme.typography.titleMedium,
                    fontWeight = FontWeight.Bold,
                    color = MaterialTheme.colorScheme.onBackground
                )
                Row(
                    verticalAlignment = Alignment.CenterVertically,
                    modifier = Modifier.clickable {
                        // Could navigate to a "see all" page
                    }
                ) {
                    Text(
                        text = "更多",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.primary
                    )
                    Spacer(modifier = Modifier.width(2.dp))
                    Icon(
                        imageVector = Icons.AutoMirrored.Filled.ArrowForward,
                        contentDescription = null,
                        tint = MaterialTheme.colorScheme.primary,
                        modifier = Modifier.height(14.dp)
                    )
                }
            }
        }

        // Product grid items
        items(uiState.products, key = { it.id }) { product ->
            ProductCard(
                product = product,
                onClick = {
                    navController.navigate(Screen.ProductDetail.createRoute(product.id))
                },
                modifier = Modifier.padding(
                    start = if (uiState.products.indexOf(product) % 2 == 0) 16.dp else 0.dp,
                    end = if (uiState.products.indexOf(product) % 2 == 1) 16.dp else 0.dp
                )
            )
        }
    }
}
