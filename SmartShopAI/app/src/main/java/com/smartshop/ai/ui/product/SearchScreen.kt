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
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.navigation.NavHostController
import com.smartshop.ai.data.mock.MockData
import com.smartshop.ai.data.model.Product
import com.smartshop.ai.ui.components.CategoryChip
import com.smartshop.ai.ui.components.ProductCard
import com.smartshop.ai.ui.components.SmartShopSearchBar
import com.smartshop.ai.ui.navigation.Screen
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

// ==================== ViewModel ====================

data class SearchUiState(
    val query: String = "",
    val results: List<Product> = emptyList(),
    val searchHistory: List<String> = listOf("蓝牙耳机", "华为手机", "咖啡机", "瑜伽垫"),
    val selectedCategoryId: String? = null
)

class SearchViewModel : ViewModel() {

    private val _uiState = MutableStateFlow(SearchUiState())
    val uiState: StateFlow<SearchUiState> = _uiState.asStateFlow()

    fun updateQuery(newQuery: String) {
        val results = if (newQuery.isBlank()) {
            emptyList()
        } else {
            val filtered = MockData.searchProducts(newQuery)
            val catId = _uiState.value.selectedCategoryId
            if (catId != null) filtered.filter { it.categoryId == catId } else filtered
        }
        _uiState.value = _uiState.value.copy(query = newQuery, results = results)
    }

    fun search(query: String) {
        if (query.isBlank()) return
        val currentHistory = _uiState.value.searchHistory.toMutableList()
        currentHistory.remove(query)
        currentHistory.add(0, query)
        _uiState.value = _uiState.value.copy(
            searchHistory = currentHistory.take(10)
        )
        updateQuery(query)
    }

    fun clearHistory() {
        _uiState.value = _uiState.value.copy(searchHistory = emptyList())
    }

    fun selectCategory(categoryId: String?) {
        val newCatId = if (_uiState.value.selectedCategoryId == categoryId) null else categoryId
        _uiState.value = _uiState.value.copy(selectedCategoryId = newCatId)
        // Re-filter with current query
        updateQuery(_uiState.value.query)
    }
}

// ==================== Screen ====================

@OptIn(ExperimentalMaterial3Api::class, ExperimentalLayoutApi::class)
@Composable
fun SearchScreen(
    navController: NavHostController,
    viewModel: SearchViewModel = viewModel()
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
                // Empty state: show history + suggestions
                SearchEmptyContent(
                    history = uiState.searchHistory,
                    suggestions = MockData.quickSuggestions,
                    onHistoryClick = { viewModel.search(it) },
                    onSuggestionClick = { viewModel.search(it) },
                    onClearHistory = { viewModel.clearHistory() }
                )
            } else {
                // Category filter row
                LazyRow(
                    contentPadding = PaddingValues(horizontal = 16.dp),
                    horizontalArrangement = Arrangement.spacedBy(8.dp)
                ) {
                    items(MockData.categories, key = { it.id }) { category ->
                        CategoryChip(
                            category = category,
                            selected = uiState.selectedCategoryId == category.id,
                            onClick = { viewModel.selectCategory(category.id) }
                        )
                    }
                }

                Spacer(modifier = Modifier.height(12.dp))

                // Results grid
                if (uiState.results.isEmpty()) {
                    Column(
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(top = 60.dp),
                        horizontalAlignment = Alignment.CenterHorizontally
                    ) {
                        Text(
                            text = "未找到相关商品",
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
                        items(uiState.results, key = { it.id }) { product ->
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
