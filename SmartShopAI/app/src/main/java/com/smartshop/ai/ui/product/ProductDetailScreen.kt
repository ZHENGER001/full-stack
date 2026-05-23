package com.smartshop.ai.ui.product

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
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
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.FavoriteBorder
import androidx.compose.material.icons.filled.Favorite
import androidx.compose.material.icons.filled.Share
import androidx.compose.material.icons.filled.Star
import androidx.compose.material3.BottomAppBar
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Divider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Scaffold
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
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextDecoration
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import android.widget.Toast
import coil.compose.AsyncImage
import coil.request.CachePolicy
import coil.request.ImageRequest
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import androidx.navigation.NavHostController
import com.smartshop.ai.data.model.Product
import com.smartshop.ai.data.account.AccountRepository
import com.smartshop.ai.data.cart.CartRepository
import com.smartshop.ai.data.product.ProductRepository
import com.smartshop.ai.ui.components.PaymentPasswordDialog
import com.smartshop.ai.ui.components.ProductCard
import com.smartshop.ai.ui.components.RatingBar
import com.smartshop.ai.ui.navigation.Screen
import com.smartshop.ai.ui.theme.Discount
import com.smartshop.ai.ui.theme.OriginalPriceColor
import com.smartshop.ai.ui.theme.PriceColor
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import javax.inject.Inject

data class ProductDetailUiState(
    val product: Product? = null,
    val relatedProducts: List<Product> = emptyList(),
    val isLoading: Boolean = false,
    val isCartActionLoading: Boolean = false,
    val isFavoriteActionLoading: Boolean = false,
    val isFavorited: Boolean = false,
    val pendingOrderId: String? = null,
    val pendingPaymentAmount: Double = 0.0,
    val isPaymentLoading: Boolean = false,
    val paymentError: String? = null,
    val errorMessage: String? = null
)

@HiltViewModel
class ProductDetailViewModel @Inject constructor(
    private val productRepository: ProductRepository,
    private val cartRepository: CartRepository,
    private val accountRepository: AccountRepository
) : ViewModel() {
    private val _uiState = MutableStateFlow(ProductDetailUiState(isLoading = true))
    val uiState: StateFlow<ProductDetailUiState> = _uiState.asStateFlow()

    fun load(productId: String) {
        if (_uiState.value.product?.id == productId) return
        viewModelScope.launch {
            val cachedProduct = productRepository.getCachedProduct(productId)
            _uiState.value = ProductDetailUiState(product = cachedProduct, isLoading = true)
            runCatching { productRepository.getProductDetail(productId) }.onSuccess { product ->
                _uiState.value = _uiState.value.copy(
                    product = product,
                    isLoading = false,
                    errorMessage = null
                )
                recordFootprint(product.id)
                loadRelated(product)
            }.onFailure { error ->
                _uiState.value = ProductDetailUiState(
                    product = cachedProduct,
                    isLoading = false,
                    errorMessage = error.message ?: "商品详情接口暂不可用"
                )
            }
        }
    }

    private fun recordFootprint(productId: String) {
        viewModelScope.launch {
            runCatching { accountRepository.addFootprint(productId) }
        }
    }

    private fun loadRelated(product: Product) {
        viewModelScope.launch {
            runCatching {
                productRepository.getProducts(category = product.category, limit = 12)
                    .filter { it.id != product.id }
                    .take(10)
            }.onSuccess { related ->
                _uiState.value = _uiState.value.copy(relatedProducts = related)
            }
        }
    }

    fun addToCart(
        productId: String,
        onSuccess: () -> Unit = {},
        onError: (String) -> Unit = {}
    ) {
        if (_uiState.value.isCartActionLoading) return
        viewModelScope.launch {
            _uiState.value = _uiState.value.copy(isCartActionLoading = true)
            runCatching { cartRepository.addProduct(productId) }
                .onSuccess {
                    _uiState.value = _uiState.value.copy(isCartActionLoading = false)
                    onSuccess()
                }
                .onFailure { error ->
                    _uiState.value = _uiState.value.copy(isCartActionLoading = false)
                    onError(error.message ?: "购物车接口暂不可用")
                }
        }
    }

    fun addFavorite(productId: String, onSuccess: () -> Unit = {}, onError: (String) -> Unit = {}) {
        if (_uiState.value.isFavoriteActionLoading) return
        viewModelScope.launch {
            _uiState.value = _uiState.value.copy(isFavoriteActionLoading = true)
            runCatching { accountRepository.addFavorite(productId) }
                .onSuccess {
                    _uiState.value = _uiState.value.copy(
                        isFavoriteActionLoading = false,
                        isFavorited = true
                    )
                    onSuccess()
                }
                .onFailure { error ->
                    _uiState.value = _uiState.value.copy(isFavoriteActionLoading = false)
                    onError(error.message ?: "收藏接口暂不可用")
                }
        }
    }

    fun buyNow(productId: String, onError: (String) -> Unit = {}) {
        if (_uiState.value.isCartActionLoading) return
        viewModelScope.launch {
            _uiState.value = _uiState.value.copy(isCartActionLoading = true, paymentError = null)
            runCatching { accountRepository.createOrderForProduct(productId) }
                .onSuccess { order ->
                    _uiState.value = _uiState.value.copy(
                        isCartActionLoading = false,
                        pendingOrderId = order.id,
                        pendingPaymentAmount = order.totalAmount
                    )
                }
                .onFailure { error ->
                    _uiState.value = _uiState.value.copy(isCartActionLoading = false)
                    onError(error.message ?: "创建订单失败")
                }
        }
    }

    fun dismissPayment() {
        _uiState.value = _uiState.value.copy(
            pendingOrderId = null,
            pendingPaymentAmount = 0.0,
            paymentError = null,
            isPaymentLoading = false
        )
    }

    fun payPendingOrder(password: String, onSuccess: () -> Unit = {}) {
        val orderId = _uiState.value.pendingOrderId ?: return
        viewModelScope.launch {
            _uiState.value = _uiState.value.copy(isPaymentLoading = true, paymentError = null)
            runCatching { accountRepository.payOrder(orderId, password) }
                .onSuccess {
                    dismissPayment()
                    onSuccess()
                }
                .onFailure { error ->
                    _uiState.value = _uiState.value.copy(
                        isPaymentLoading = false,
                        paymentError = error.message ?: "支付失败"
                    )
                }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ProductDetailScreen(
    productId: String,
    navController: NavHostController,
    viewModel: ProductDetailViewModel = hiltViewModel()
) {
    LaunchedEffect(productId) {
        viewModel.load(productId)
    }
    val uiState by viewModel.uiState.collectAsState()
    val product = uiState.product
    val context = LocalContext.current

    if (product == null) {
        Box(
            modifier = Modifier.fillMaxSize(),
            contentAlignment = Alignment.Center
        ) {
            Text(
                text = if (uiState.isLoading) "正在加载商品..." else uiState.errorMessage ?: "商品不存在",
                style = MaterialTheme.typography.bodyLarge,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
        }
        return
    }

    val relatedProducts = uiState.relatedProducts
    if (uiState.pendingOrderId != null) {
        PaymentPasswordDialog(
            amount = uiState.pendingPaymentAmount,
            isLoading = uiState.isPaymentLoading,
            errorMessage = uiState.paymentError,
            onDismiss = { viewModel.dismissPayment() },
            onConfirm = { password ->
                viewModel.payPendingOrder(password) {
                    Toast.makeText(context, "支付成功，订单已生成", Toast.LENGTH_SHORT).show()
                    navController.navigate(Screen.Orders.route)
                }
            }
        )
    }
    val detailImageRequest = remember(product.imageUrl) {
        ImageRequest.Builder(context)
            .data(product.imageUrl)
            .crossfade(false)
            .memoryCachePolicy(CachePolicy.ENABLED)
            .diskCachePolicy(CachePolicy.ENABLED)
            .size(900, 900)
            .build()
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = {
                    Text(
                        text = "商品详情",
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis
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
                actions = {
                    IconButton(onClick = { /* share */ }) {
                        Icon(
                            imageVector = Icons.Default.Share,
                            contentDescription = "分享"
                        )
                    }
                },
                colors = TopAppBarDefaults.topAppBarColors(
                    containerColor = MaterialTheme.colorScheme.background
                )
            )
        },
        bottomBar = {
            BottomAppBar(
                containerColor = MaterialTheme.colorScheme.surface,
                tonalElevation = 8.dp
            ) {
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(horizontal = 12.dp),
                    horizontalArrangement = Arrangement.spacedBy(8.dp),
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    // Favorite button
                    OutlinedButton(
                        onClick = {
                            viewModel.addFavorite(
                                product.id,
                                onSuccess = {
                                    Toast.makeText(context, "已添加到我的收藏", Toast.LENGTH_SHORT).show()
                                },
                                onError = { message ->
                                    Toast.makeText(context, message, Toast.LENGTH_SHORT).show()
                                }
                            )
                        },
                        modifier = Modifier.weight(1f),
                        enabled = !uiState.isFavoriteActionLoading
                    ) {
                        Icon(
                            imageVector = if (uiState.isFavorited) Icons.Default.Favorite else Icons.Default.FavoriteBorder,
                            contentDescription = null,
                            modifier = Modifier.height(18.dp)
                        )
                        Spacer(modifier = Modifier.width(4.dp))
                        Text("收藏")
                    }

                    // Add to cart
                    Button(
                        onClick = {
                            viewModel.addToCart(
                                productId = product.id,
                                onSuccess = {
                                    Toast.makeText(context, "已加入购物车", Toast.LENGTH_SHORT).show()
                                },
                                onError = { message ->
                                    Toast.makeText(context, message, Toast.LENGTH_SHORT).show()
                                }
                            )
                        },
                        modifier = Modifier.weight(1.5f),
                        enabled = !uiState.isCartActionLoading,
                        colors = ButtonDefaults.buttonColors(
                            containerColor = MaterialTheme.colorScheme.primary
                        )
                    ) {
                        Text("加入购物车")
                    }

                    // Buy now
                    Button(
                        onClick = {
                            viewModel.buyNow(product.id) { message ->
                                Toast.makeText(context, message, Toast.LENGTH_SHORT).show()
                            }
                        },
                        modifier = Modifier.weight(1.5f),
                        enabled = !uiState.isCartActionLoading,
                        colors = ButtonDefaults.buttonColors(
                            containerColor = PriceColor
                        )
                    ) {
                        Text("立即购买")
                    }
                }
            }
        }
    ) { innerPadding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(innerPadding)
                .verticalScroll(rememberScrollState())
        ) {
            // Image area (placeholder)
            Box(
                modifier = Modifier
                    .fillMaxWidth()
                    .height(300.dp)
                    .background(
                        brush = Brush.linearGradient(
                            colors = listOf(
                                Color(0xFFE8F0FE),
                                Color(0xFFD2E3FC)
                            )
                        )
                    ),
                contentAlignment = Alignment.Center
            ) {
                AsyncImage(
                    model = detailImageRequest,
                    contentDescription = product.name,
                    contentScale = ContentScale.Crop,
                    modifier = Modifier.matchParentSize()
                )
                Column(horizontalAlignment = Alignment.CenterHorizontally) {
                    Box(
                        modifier = Modifier
                            .background(
                                color = MaterialTheme.colorScheme.primaryContainer.copy(alpha = 0.9f),
                                shape = RoundedCornerShape(8.dp)
                            )
                            .padding(horizontal = 12.dp, vertical = 4.dp)
                    ) {
                        Text(
                            text = product.category,
                            style = MaterialTheme.typography.labelMedium,
                            color = MaterialTheme.colorScheme.primary
                        )
                    }
                }
            }

            // Price section
            Column(modifier = Modifier.padding(16.dp)) {
                Row(
                    verticalAlignment = Alignment.Bottom,
                    horizontalArrangement = Arrangement.spacedBy(8.dp)
                ) {
                    Text(
                        text = "¥",
                        color = PriceColor,
                        fontSize = 18.sp,
                        fontWeight = FontWeight.Bold
                    )
                    Text(
                        text = "%.0f".format(product.price),
                        color = PriceColor,
                        fontSize = 32.sp,
                        fontWeight = FontWeight.Bold
                    )
                    product.originalPrice?.let { origPrice ->
                        Text(
                            text = "¥${"%.0f".format(origPrice)}",
                            color = OriginalPriceColor,
                            fontSize = 14.sp,
                            textDecoration = TextDecoration.LineThrough,
                            modifier = Modifier.padding(bottom = 4.dp)
                        )
                    }
                    product.discount?.let { discountPercent ->
                        Box(
                            modifier = Modifier
                                .padding(bottom = 4.dp)
                                .background(
                                    color = Discount,
                                    shape = RoundedCornerShape(4.dp)
                                )
                                .padding(horizontal = 6.dp, vertical = 2.dp)
                        ) {
                            Text(
                                text = "-${discountPercent}%",
                                color = Color.White,
                                fontSize = 12.sp,
                                fontWeight = FontWeight.Bold
                            )
                        }
                    }
                }

                Spacer(modifier = Modifier.height(12.dp))

                // Product name
                Text(
                    text = product.name,
                    style = MaterialTheme.typography.titleLarge,
                    fontWeight = FontWeight.Bold,
                    color = MaterialTheme.colorScheme.onSurface
                )

                Spacer(modifier = Modifier.height(6.dp))

                // Brand
                if (product.brand.isNotEmpty()) {
                    Box(
                        modifier = Modifier
                            .background(
                                color = MaterialTheme.colorScheme.primaryContainer,
                                shape = RoundedCornerShape(4.dp)
                            )
                            .padding(horizontal = 8.dp, vertical = 2.dp)
                    ) {
                        Text(
                            text = product.brand,
                            style = MaterialTheme.typography.labelMedium,
                            color = MaterialTheme.colorScheme.primary,
                            fontWeight = FontWeight.Medium
                        )
                    }
                }

                Spacer(modifier = Modifier.height(8.dp))

                // Rating
                Row(verticalAlignment = Alignment.CenterVertically) {
                    RatingBar(rating = product.rating, starSize = 18.dp)
                    Spacer(modifier = Modifier.width(8.dp))
                    Text(
                        text = "%.1f".format(product.rating),
                        style = MaterialTheme.typography.bodyMedium,
                        fontWeight = FontWeight.SemiBold,
                        color = MaterialTheme.colorScheme.onSurface
                    )
                    Spacer(modifier = Modifier.width(4.dp))
                    Text(
                        text = "(${product.reviewCount}条评价)",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant
                    )
                }

                Spacer(modifier = Modifier.height(6.dp))

                // Description
                Text(
                    text = product.description,
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    lineHeight = 22.sp
                )
            }

            Divider(
                modifier = Modifier.padding(horizontal = 16.dp),
                color = MaterialTheme.colorScheme.outlineVariant
            )

            // AI Comment section
            if (product.aiComment.isNotEmpty()) {
                Column(modifier = Modifier.padding(16.dp)) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Icon(
                            imageVector = Icons.Default.Star,
                            contentDescription = null,
                            tint = MaterialTheme.colorScheme.primary,
                            modifier = Modifier.height(20.dp)
                        )
                        Spacer(modifier = Modifier.width(6.dp))
                        Text(
                            text = "AI 智能点评",
                            style = MaterialTheme.typography.titleMedium,
                            fontWeight = FontWeight.Bold,
                            color = MaterialTheme.colorScheme.onBackground
                        )
                    }

                    Spacer(modifier = Modifier.height(8.dp))

                    Card(
                        modifier = Modifier.fillMaxWidth(),
                        shape = RoundedCornerShape(12.dp),
                        colors = CardDefaults.cardColors(
                            containerColor = MaterialTheme.colorScheme.primaryContainer.copy(alpha = 0.4f)
                        )
                    ) {
                        Text(
                            text = product.aiComment,
                            style = MaterialTheme.typography.bodyMedium,
                            color = MaterialTheme.colorScheme.onSurface,
                            lineHeight = 22.sp,
                            modifier = Modifier.padding(16.dp)
                        )
                    }
                }
            }

            Divider(
                modifier = Modifier.padding(horizontal = 16.dp),
                color = MaterialTheme.colorScheme.outlineVariant
            )

            // Specs section
            if (product.specs.isNotEmpty()) {
                Column(modifier = Modifier.padding(16.dp)) {
                    Text(
                        text = "商品规格",
                        style = MaterialTheme.typography.titleMedium,
                        fontWeight = FontWeight.Bold,
                        color = MaterialTheme.colorScheme.onBackground
                    )

                    Spacer(modifier = Modifier.height(8.dp))

                    Card(
                        modifier = Modifier.fillMaxWidth(),
                        shape = RoundedCornerShape(12.dp),
                        colors = CardDefaults.cardColors(
                            containerColor = MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.4f)
                        )
                    ) {
                        Column(modifier = Modifier.padding(12.dp)) {
                            product.specs.entries.forEachIndexed { index, (key, value) ->
                                Row(
                                    modifier = Modifier
                                        .fillMaxWidth()
                                        .padding(vertical = 8.dp),
                                    horizontalArrangement = Arrangement.SpaceBetween
                                ) {
                                    Text(
                                        text = key,
                                        style = MaterialTheme.typography.bodyMedium,
                                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                                        modifier = Modifier.weight(1f)
                                    )
                                    Text(
                                        text = value,
                                        style = MaterialTheme.typography.bodyMedium,
                                        fontWeight = FontWeight.Medium,
                                        color = MaterialTheme.colorScheme.onSurface,
                                        modifier = Modifier.weight(1.5f)
                                    )
                                }
                                if (index < product.specs.size - 1) {
                                    Divider(
                                        color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = 0.5f)
                                    )
                                }
                            }
                        }
                    }
                }
            }

            if (product.skuSummaries.isNotEmpty()) {
                DetailTextSection(
                    title = "可选 SKU",
                    lines = product.skuSummaries.take(6)
                )
            }

            if (product.faqSummaries.isNotEmpty()) {
                DetailTextSection(
                    title = "官方 FAQ",
                    lines = product.faqSummaries.take(3)
                )
            }

            if (product.reviewSummaries.isNotEmpty()) {
                DetailTextSection(
                    title = "用户评价",
                    lines = product.reviewSummaries.take(3)
                )
            }

            // Related products
            if (relatedProducts.isNotEmpty()) {
                Divider(
                    modifier = Modifier.padding(horizontal = 16.dp),
                    color = MaterialTheme.colorScheme.outlineVariant
                )

                Column(modifier = Modifier.padding(vertical = 16.dp)) {
                    Text(
                        text = "相关推荐",
                        style = MaterialTheme.typography.titleMedium,
                        fontWeight = FontWeight.Bold,
                        color = MaterialTheme.colorScheme.onBackground,
                        modifier = Modifier.padding(horizontal = 16.dp)
                    )

                    Spacer(modifier = Modifier.height(8.dp))

                    LazyRow(
                        contentPadding = PaddingValues(horizontal = 16.dp),
                        horizontalArrangement = Arrangement.spacedBy(12.dp)
                    ) {
                        items(relatedProducts, key = { it.id }) { relatedProduct ->
                            ProductCard(
                                product = relatedProduct,
                                onClick = {
                                    navController.navigate(
                                        Screen.ProductDetail.createRoute(relatedProduct.id)
                                    )
                                },
                                fixedWidth = 180.dp
                            )
                        }
                    }
                }
            }

            // Bottom spacing
            Spacer(modifier = Modifier.height(16.dp))
        }
    }
}

@Composable
private fun DetailTextSection(
    title: String,
    lines: List<String>
) {
    Divider(
        modifier = Modifier.padding(horizontal = 16.dp),
        color = MaterialTheme.colorScheme.outlineVariant
    )
    Column(modifier = Modifier.padding(16.dp)) {
        Text(
            text = title,
            style = MaterialTheme.typography.titleMedium,
            fontWeight = FontWeight.Bold,
            color = MaterialTheme.colorScheme.onBackground
        )
        Spacer(modifier = Modifier.height(8.dp))
        lines.forEach { line ->
            Text(
                text = line,
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                lineHeight = 21.sp,
                modifier = Modifier.padding(bottom = 8.dp)
            )
        }
    }
}
