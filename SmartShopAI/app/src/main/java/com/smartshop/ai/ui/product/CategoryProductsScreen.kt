package com.smartshop.ai.ui.product

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.grid.GridCells
import androidx.compose.foundation.lazy.grid.LazyVerticalGrid
import androidx.compose.foundation.lazy.grid.items
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChip
import androidx.compose.material3.FilterChipDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
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
import com.smartshop.ai.data.model.Product
import com.smartshop.ai.ui.components.ProductCard
import com.smartshop.ai.ui.navigation.Screen
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

// ==================== ViewModel ====================

enum class SortOption(val label: String) {
    DEFAULT("综合"),
    PRICE_ASC("价格升序"),
    PRICE_DESC("价格降序"),
    RATING("评分")
}

data class CategoryProductsUiState(
    val categoryId: String = "",
    val categoryName: String = "",
    val products: List<Product> = emptyList(),
    val sortOption: SortOption = SortOption.DEFAULT
)

class CategoryProductsViewModel : ViewModel() {

    private val _uiState = MutableStateFlow(CategoryProductsUiState())
    val uiState: StateFlow<CategoryProductsUiState> = _uiState.asStateFlow()

    fun loadCategory(categoryId: String) {
        if (_uiState.value.categoryId == categoryId) return
        val category = MockData.categories.find { it.id == categoryId }
        val products = MockData.getProductsByCategory(categoryId)
        _uiState.value = CategoryProductsUiState(
            categoryId = categoryId,
            categoryName = category?.name ?: "分类",
            products = products,
            sortOption = SortOption.DEFAULT
        )
    }

    fun setSortOption(option: SortOption) {
        val current = _uiState.value
        if (current.sortOption == option) return
        val sorted = when (option) {
            SortOption.DEFAULT -> MockData.getProductsByCategory(current.categoryId)
            SortOption.PRICE_ASC -> current.products.sortedBy { it.price }
            SortOption.PRICE_DESC -> current.products.sortedByDescending { it.price }
            SortOption.RATING -> current.products.sortedByDescending { it.rating }
        }
        _uiState.value = current.copy(sortOption = option, products = sorted)
    }
}

// ==================== Screen ====================

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun CategoryProductsScreen(
    categoryId: String,
    navController: NavHostController,
    viewModel: CategoryProductsViewModel = viewModel()
) {
    viewModel.loadCategory(categoryId)
    val uiState by viewModel.uiState.collectAsState()

    Scaffold(
        topBar = {
            TopAppBar(
                title = {
                    Text(
                        text = uiState.categoryName,
                        fontWeight = FontWeight.Bold
                    )
                },
                navigationIcon = {
                    IconButton(onClick = { navController.popBackStack() }) {
                        Icon(
                            imageVector = Icons.AutoMirrored.Filled.ArrowBack,
                            contentDescription = "返回"
                        )
                    }
                },
                colors = TopAppBarDefaults.topAppBarColors(
                    containerColor = MaterialTheme.colorScheme.background
                )
            )
        }
    ) { innerPadding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(innerPadding)
        ) {
            // Sort options row
            LazyRow(
                contentPadding = PaddingValues(horizontal = 16.dp),
                horizontalArrangement = Arrangement.spacedBy(8.dp),
                modifier = Modifier.padding(vertical = 8.dp)
            ) {
                items(SortOption.entries.toList()) { option ->
                    FilterChip(
                        selected = uiState.sortOption == option,
                        onClick = { viewModel.setSortOption(option) },
                        label = {
                            Text(
                                text = option.label,
                                style = MaterialTheme.typography.labelLarge,
                                fontWeight = if (uiState.sortOption == option) FontWeight.SemiBold else FontWeight.Normal
                            )
                        },
                        colors = FilterChipDefaults.filterChipColors(
                            containerColor = MaterialTheme.colorScheme.surface,
                            selectedContainerColor = MaterialTheme.colorScheme.primaryContainer,
                            selectedLabelColor = MaterialTheme.colorScheme.primary
                        )
                    )
                }
            }

            if (uiState.products.isEmpty()) {
                Column(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(top = 80.dp),
                    horizontalAlignment = Alignment.CenterHorizontally
                ) {
                    Text(
                        text = "该分类暂无商品",
                        style = MaterialTheme.typography.bodyLarge,
                        color = MaterialTheme.colorScheme.onSurfaceVariant
                    )
                }
            } else {
                LazyVerticalGrid(
                    columns = GridCells.Fixed(2),
                    contentPadding = PaddingValues(horizontal = 16.dp, vertical = 8.dp),
                    horizontalArrangement = Arrangement.spacedBy(12.dp),
                    verticalArrangement = Arrangement.spacedBy(12.dp)
                ) {
                    items(uiState.products, key = { it.id }) { product ->
                        ProductCard(
                            product = product,
                            onClick = {
                                navController.navigate(
                                    Screen.ProductDetail.createRoute(product.id)
                                )
                            }
                        )
                    }
                }
            }
        }
    }
}
