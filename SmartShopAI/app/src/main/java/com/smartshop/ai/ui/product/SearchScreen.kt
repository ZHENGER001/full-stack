package com.smartshop.ai.ui.product

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
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
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.History
import androidx.compose.material3.AssistChip
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SuggestionChip
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import androidx.navigation.NavHostController
import com.smartshop.ai.data.mock.MockData
import com.smartshop.ai.data.model.Category
import com.smartshop.ai.data.model.Product
import com.smartshop.ai.data.product.ProductRepository
import com.smartshop.ai.ui.components.CategoryChip
import com.smartshop.ai.ui.components.ProductCard
import com.smartshop.ai.ui.components.SmartShopSearchBar
import com.smartshop.ai.ui.navigation.Screen
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import javax.inject.Inject

// ==================== ViewModel ====================

data class SearchUiState(
    val query: String = "",
    val allProducts: List<Product> = emptyList(),
    val results: List<Product> = emptyList(),
    val searchHistory: List<String> = listOf("蓝牙耳机", "华为手机", "咖啡机", "瑜伽垫"),
    val categories: List<Category> = emptyList(),
    val selectedCategoryId: String? = null,
    val isLoading: Boolean = true,
    val errorMessage: String? = null
)

@HiltViewModel
class SearchViewModel @Inject constructor(
    private val productRepository: ProductRepository
) : ViewModel() {

    private val _uiState = MutableStateFlow(SearchUiState())
    val uiState: StateFlow<SearchUiState> = _uiState.asStateFlow()
    private var searchJob: Job? = null

    init {
        viewModelScope.launch {
            val cachedProducts = productRepository.cachedProducts()
            val cachedCategories = productRepository.cachedCategories()
            if (cachedProducts.isNotEmpty()) {
                _uiState.value = _uiState.value.copy(
                    categories = cachedCategories,
                    allProducts = cachedProducts,
                    isLoading = false,
                    errorMessage = null
                )
            }
            runCatching {
                val categories = productRepository.getCategories()
                val products = productRepository.getProducts(sort = "rating")
                categories to products
            }.onSuccess { (categories, products) ->
                _uiState.value = _uiState.value.copy(
                    categories = categories,
                    allProducts = products,
                    isLoading = false,
                    errorMessage = null
                )
            }.onFailure { error ->
                _uiState.value = _uiState.value.copy(
                    isLoading = false,
                    errorMessage = error.message ?: "商品接口暂不可用"
                )
            }
        }
    }

    fun showAllProducts() {
        searchJob?.cancel()
        val category = _uiState.value.selectedCategoryId
        val baseProducts = productRepository.cachedProducts()
        val visibleProducts = if (category == null) {
            baseProducts
        } else {
            baseProducts.filter { it.categoryId == category || it.category == category }
        }
        _uiState.value = _uiState.value.copy(
            query = "",
            allProducts = visibleProducts,
            results = emptyList(),
            isLoading = false,
            errorMessage = null
        )
    }

    fun updateQuery(newQuery: String) {
        _uiState.value = _uiState.value.copy(query = newQuery)
        searchJob?.cancel()
        if (newQuery.isBlank()) {
            showAllProducts()
            return
        }
        searchJob = viewModelScope.launch {
            delay(250)
            runSearch(newQuery)
        }
    }

    fun search(query: String) {
        if (query.isBlank()) return
        val currentHistory = _uiState.value.searchHistory.toMutableList()
        currentHistory.remove(query)
        currentHistory.add(0, query)
        _uiState.value = _uiState.value.copy(
            query = query,
            searchHistory = currentHistory.take(10)
        )
        searchJob?.cancel()
        viewModelScope.launch { runSearch(query) }
    }

    fun clearHistory() {
        _uiState.value = _uiState.value.copy(searchHistory = emptyList())
    }

    fun selectCategory(categoryId: String?) {
        val newCatId = if (_uiState.value.selectedCategoryId == categoryId) null else categoryId
        _uiState.value = _uiState.value.copy(selectedCategoryId = newCatId)
        searchJob?.cancel()
        val query = _uiState.value.query
        if (query.isNotBlank()) {
            viewModelScope.launch { runSearch(query) }
        } else {
            showAllProducts()
        }
    }

    private suspend fun runSearch(query: String) {
        val category = _uiState.value.selectedCategoryId
        val localResults = productRepository.searchCachedProducts(query, category)
        _uiState.value = _uiState.value.copy(
            results = localResults,
            isLoading = localResults.isEmpty(),
            errorMessage = null
        )
        runCatching {
            productRepository.searchProducts(query, category)
        }.onSuccess { results ->
            _uiState.value = _uiState.value.copy(
                results = results,
                isLoading = false,
                errorMessage = null
            )
        }.onFailure { error ->
            _uiState.value = _uiState.value.copy(
                results = localResults,
                isLoading = false,
                errorMessage = if (localResults.isEmpty()) {
                    error.message ?: "搜索接口暂不可用"
                } else {
                    null
                }
            )
        }
    }
}

// ==================== Screen ====================

@OptIn(ExperimentalMaterial3Api::class, ExperimentalLayoutApi::class)
@Composable
fun SearchScreen(
    navController: NavHostController,
    viewModel: SearchViewModel = hiltViewModel()
) {
    val uiState by viewModel.uiState.collectAsState()
    val focusRequester = remember { FocusRequester() }

    LaunchedEffect(Unit) {
        focusRequester.requestFocus()
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = {},
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
            // Search bar
            SmartShopSearchBar(
                query = uiState.query,
                onQueryChange = { viewModel.updateQuery(it) },
                onSearch = { viewModel.search(it) },
                modifier = Modifier
                    .padding(horizontal = 16.dp)
                    .focusRequester(focusRequester),
                placeholder = "搜索商品、品牌、品类..."
            )

            Spacer(modifier = Modifier.height(12.dp))

            if (uiState.query.isBlank()) {
                LazyVerticalGrid(
                    columns = GridCells.Fixed(2),
                    modifier = Modifier.weight(1f),
                    contentPadding = PaddingValues(horizontal = 16.dp, vertical = 8.dp),
                    horizontalArrangement = Arrangement.spacedBy(12.dp),
                    verticalArrangement = Arrangement.spacedBy(12.dp)
                ) {
                    item(span = { GridItemSpan(2) }) {
                        SearchEmptyContent(
                            history = uiState.searchHistory,
                            suggestions = MockData.quickSuggestions,
                            onHistoryClick = { viewModel.search(it) },
                            onSuggestionClick = { viewModel.search(it) },
                            onClearHistory = { viewModel.clearHistory() }
                        )
                    }
                    item(span = { GridItemSpan(2) }) {
                        LazyRow(
                            horizontalArrangement = Arrangement.spacedBy(8.dp)
                        ) {
                            items(uiState.categories, key = { it.id }) { category ->
                                CategoryChip(
                                    category = category,
                                    selected = uiState.selectedCategoryId == category.id,
                                    onClick = { viewModel.selectCategory(category.id) }
                                )
                            }
                        }
                    }
                    item(span = { GridItemSpan(2) }) {
                        Text(
                            text = if (uiState.selectedCategoryId == null) {
                                "全部数据集商品 ${uiState.allProducts.size} 件"
                            } else {
                                "${uiState.selectedCategoryId} ${uiState.allProducts.size} 件"
                            },
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                            modifier = Modifier.padding(top = 4.dp)
                        )
                    }
                    if (uiState.isLoading) {
                        item(span = { GridItemSpan(2) }) {
                            Text(
                                text = "正在加载数据集商品...",
                                style = MaterialTheme.typography.bodyMedium,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                                modifier = Modifier.padding(vertical = 24.dp)
                            )
                        }
                    } else {
                        items(
                            uiState.allProducts,
                            key = { it.id },
                            contentType = { "product" }
                        ) { product ->
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
            } else {
                // Category filter row
                LazyRow(
                    contentPadding = PaddingValues(horizontal = 16.dp),
                    horizontalArrangement = Arrangement.spacedBy(8.dp)
                ) {
                    items(uiState.categories, key = { it.id }) { category ->
                        CategoryChip(
                            category = category,
                            selected = uiState.selectedCategoryId == category.id,
                            onClick = { viewModel.selectCategory(category.id) }
                        )
                    }
                }

                Spacer(modifier = Modifier.height(12.dp))

                // Results grid
                if (uiState.isLoading) {
                    Column(
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(top = 60.dp),
                        horizontalAlignment = Alignment.CenterHorizontally
                    ) {
                        Text(
                            text = "正在搜索数据集商品...",
                            style = MaterialTheme.typography.bodyLarge,
                            color = MaterialTheme.colorScheme.onSurfaceVariant
                        )
                    }
                } else if (uiState.results.isEmpty()) {
                    Column(
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(top = 60.dp),
                        horizontalAlignment = Alignment.CenterHorizontally
                    ) {
                        Text(
                            text = uiState.errorMessage ?: "未找到相关商品",
                            style = MaterialTheme.typography.bodyLarge,
                            color = MaterialTheme.colorScheme.onSurfaceVariant
                        )
                        Spacer(modifier = Modifier.height(4.dp))
                        Text(
                            text = "换个关键词试试吧",
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.6f)
                        )
                    }
                } else {
                    LazyVerticalGrid(
                        columns = GridCells.Fixed(2),
                        modifier = Modifier.weight(1f),
                        contentPadding = PaddingValues(horizontal = 16.dp, vertical = 8.dp),
                        horizontalArrangement = Arrangement.spacedBy(12.dp),
                        verticalArrangement = Arrangement.spacedBy(12.dp)
                    ) {
                        item(span = { GridItemSpan(2) }) {
                            Text(
                                text = "找到 ${uiState.results.size} 件商品",
                                style = MaterialTheme.typography.bodySmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                                modifier = Modifier.padding(bottom = 4.dp)
                            )
                        }
                        items(
                            uiState.results,
                            key = { it.id },
                            contentType = { "product" }
                        ) { product ->
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
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun SearchEmptyContent(
    history: List<String>,
    suggestions: List<String>,
    onHistoryClick: (String) -> Unit,
    onSuggestionClick: (String) -> Unit,
    onClearHistory: () -> Unit
) {
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = 16.dp)
    ) {
        // Search history
        if (history.isNotEmpty()) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically
            ) {
                Text(
                    text = "搜索历史",
                    style = MaterialTheme.typography.titleSmall,
                    fontWeight = FontWeight.Bold,
                    color = MaterialTheme.colorScheme.onBackground
                )
                IconButton(onClick = onClearHistory) {
                    Icon(
                        imageVector = Icons.Default.Delete,
                        contentDescription = "清除历史",
                        tint = MaterialTheme.colorScheme.onSurfaceVariant
                    )
                }
            }

            FlowRow(
                horizontalArrangement = Arrangement.spacedBy(8.dp),
                verticalArrangement = Arrangement.spacedBy(4.dp)
            ) {
                history.forEach { item ->
                    AssistChip(
                        onClick = { onHistoryClick(item) },
                        label = {
                            Row(verticalAlignment = Alignment.CenterVertically) {
                                Icon(
                                    imageVector = Icons.Default.History,
                                    contentDescription = null,
                                    modifier = Modifier.height(14.dp)
                                )
                                Spacer(modifier = Modifier.width(4.dp))
                                Text(text = item, style = MaterialTheme.typography.bodySmall)
                            }
                        }
                    )
                }
            }

            Spacer(modifier = Modifier.height(24.dp))
        }

        // Quick suggestions
        Text(
            text = "猜你想搜",
            style = MaterialTheme.typography.titleSmall,
            fontWeight = FontWeight.Bold,
            color = MaterialTheme.colorScheme.onBackground
        )
        Spacer(modifier = Modifier.height(8.dp))

        FlowRow(
            horizontalArrangement = Arrangement.spacedBy(8.dp),
            verticalArrangement = Arrangement.spacedBy(4.dp)
        ) {
            suggestions.forEach { suggestion ->
                SuggestionChip(
                    onClick = { onSuggestionClick(suggestion) },
                    label = {
                        Text(text = suggestion, style = MaterialTheme.typography.bodySmall)
                    }
                )
            }
        }
    }
}
