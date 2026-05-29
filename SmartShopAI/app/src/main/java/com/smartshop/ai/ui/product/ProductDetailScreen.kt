package com.smartshop.ai.ui.product

import android.widget.Toast
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
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
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Favorite
import androidx.compose.material.icons.filled.FavoriteBorder
import androidx.compose.material.icons.filled.Share
import androidx.compose.material.icons.filled.Star
import androidx.compose.material3.BottomAppBar
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.Divider
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SheetState
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextDecoration
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import androidx.navigation.NavHostController
import coil.compose.AsyncImage
import coil.request.CachePolicy
import coil.request.ImageRequest
import com.smartshop.ai.data.account.AccountRepository
import com.smartshop.ai.data.cart.CartRepository
import com.smartshop.ai.data.model.Order
import com.smartshop.ai.data.model.Product
import com.smartshop.ai.data.model.ProductReview
import com.smartshop.ai.data.model.ProductSku
import com.smartshop.ai.data.product.ProductRepository
import com.smartshop.ai.ui.components.ProductCard
import com.smartshop.ai.ui.components.RatingBar
import com.smartshop.ai.ui.navigation.Screen
import com.smartshop.ai.ui.payment.MockWeChatLoadingDialog
import com.smartshop.ai.ui.payment.MockWeChatPaymentSheet
import com.smartshop.ai.ui.theme.Discount
import com.smartshop.ai.ui.theme.OriginalPriceColor
import com.smartshop.ai.ui.theme.PriceColor
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import javax.inject.Inject

enum class SkuAction {
    AddToCart,
    BuyNow
}

data class ProductDetailUiState(
    val product: Product? = null,
    val relatedProducts: List<Product> = emptyList(),
    val selectedSkuId: String? = null,
    val showSkuSheet: Boolean = false,
    val skuAction: SkuAction? = null,
    val isLoading: Boolean = false,
    val isCartActionLoading: Boolean = false,
    val isFavoriteActionLoading: Boolean = false,
    val isFavorited: Boolean = false,
    val showMockPaymentLoading: Boolean = false,
    val showPaymentSheet: Boolean = false,
    val pendingOrderId: String? = null,
    val pendingPaymentAmount: Double = 0.0,
    val pendingPaymentProductName: String = "",
    val pendingPaymentSkuText: String = "",
    val isPaymentLoading: Boolean = false,
    val paymentError: String? = null,
    val errorMessage: String? = null
) {
    val selectedSku: ProductSku?
        get() = product?.skus?.firstOrNull { it.id == selectedSkuId }
}

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
            runCatching { productRepository.getProductDetail(productId) }
                .onSuccess { product ->
                    _uiState.value = _uiState.value.copy(
                        product = product,
                        isLoading = false,
                        selectedSkuId = null,
                        errorMessage = null
                    )
                    recordFootprint(product.id)
                    loadRelated(product)
                }
                .onFailure { error ->
                    _uiState.value = ProductDetailUiState(
                        product = cachedProduct,
                        isLoading = false,
                        errorMessage = error.message ?: "商品详情接口暂不可用"
                    )
                }
        }
    }

    fun selectSku(skuId: String) {
        _uiState.value = _uiState.value.copy(selectedSkuId = skuId, paymentError = null)
    }

    fun openSkuSheet(action: SkuAction) {
        _uiState.value = _uiState.value.copy(
            showSkuSheet = true,
            skuAction = action,
            selectedSkuId = null,
            paymentError = null
        )
    }

    fun dismissSkuSheet() {
        _uiState.value = _uiState.value.copy(
            showSkuSheet = false,
            skuAction = null,
            selectedSkuId = null
        )
    }

    fun addToCart(onSuccess: () -> Unit = {}, onError: (String) -> Unit = {}) {
        val state = _uiState.value
        val product = state.product ?: return
        val sku = state.selectedSku
        if (sku == null) {
            onError("请先选择规格")
            return
        }
        if (state.isCartActionLoading) return
        viewModelScope.launch {
            _uiState.value = _uiState.value.copy(isCartActionLoading = true)
            runCatching { cartRepository.addProduct(product, sku) }
                .onSuccess {
                    _uiState.value = _uiState.value.copy(
                        isCartActionLoading = false,
                        showSkuSheet = false,
                        skuAction = null,
                        selectedSkuId = null
                    )
                    onSuccess()
                }
                .onFailure { error ->
                    _uiState.value = _uiState.value.copy(isCartActionLoading = false)
                    onError(error.message ?: "加入购物车失败")
                }
        }
    }

    fun addFavorite(onSuccess: () -> Unit = {}, onError: (String) -> Unit = {}) {
        val product = _uiState.value.product ?: return
        if (_uiState.value.isFavoriteActionLoading) return
        viewModelScope.launch {
            _uiState.value = _uiState.value.copy(isFavoriteActionLoading = true)
            runCatching { accountRepository.addFavorite(product.id) }
                .onSuccess {
                    _uiState.value = _uiState.value.copy(
                        isFavoriteActionLoading = false,
                        isFavorited = true
                    )
                    onSuccess()
                }
                .onFailure { error ->
                    _uiState.value = _uiState.value.copy(isFavoriteActionLoading = false)
                    onError(error.message ?: "收藏失败")
                }
        }
    }

    fun buyNow(onError: (String) -> Unit = {}) {
        val state = _uiState.value
        val product = state.product ?: return
        val sku = state.selectedSku
        if (sku == null) {
            onError("请先选择规格")
            return
        }
        if (state.showMockPaymentLoading || state.showPaymentSheet) return
        viewModelScope.launch {
            _uiState.value = _uiState.value.copy(
                showMockPaymentLoading = true,
                paymentError = null
            )
            delay(1200)
            runCatching { accountRepository.createOrderForProduct(product, sku) }
            .onSuccess { order ->
                    _uiState.value = _uiState.value.copy(
                        showMockPaymentLoading = false,
                        showSkuSheet = false,
                        skuAction = null,
                        showPaymentSheet = true,
                        pendingOrderId = order.id,
                        pendingPaymentAmount = order.totalAmount,
                        pendingPaymentProductName = product.name,
                        pendingPaymentSkuText = sku.skuText
                    )
                }
                .onFailure { error ->
                    _uiState.value = _uiState.value.copy(showMockPaymentLoading = false)
                    onError(error.message ?: "创建订单失败")
                }
        }
    }

    fun dismissPayment() {
        _uiState.value = _uiState.value.copy(
            showPaymentSheet = false,
            pendingOrderId = null,
            pendingPaymentAmount = 0.0,
            pendingPaymentProductName = "",
            pendingPaymentSkuText = "",
            paymentError = null,
            isPaymentLoading = false
        )
    }

    fun payPendingOrder(password: String, onSuccess: (Order) -> Unit = {}) {
        val orderId = _uiState.value.pendingOrderId ?: return
        viewModelScope.launch {
            _uiState.value = _uiState.value.copy(isPaymentLoading = true, paymentError = null)
            runCatching { accountRepository.payOrder(orderId, password) }
                .onSuccess { order ->
                    _uiState.value = _uiState.value.copy(
                        isPaymentLoading = false,
                        showPaymentSheet = false
                    )
                    onSuccess(order)
                }
                .onFailure { error ->
                    _uiState.value = _uiState.value.copy(
                        isPaymentLoading = false,
                        paymentError = error.message ?: "支付失败"
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
    val paymentSheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true)
    val skuSheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true)

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

    if (uiState.showPaymentSheet && uiState.pendingOrderId != null) {
        MockWeChatPaymentSheet(
            sheetState = paymentSheetState,
            productName = uiState.pendingPaymentProductName,
            skuText = uiState.pendingPaymentSkuText,
            amount = uiState.pendingPaymentAmount,
            isLoading = uiState.isPaymentLoading,
            errorMessage = uiState.paymentError,
            onDismiss = { viewModel.dismissPayment() },
            onPasswordComplete = { password ->
                viewModel.payPendingOrder(password) {
                    navController.navigate(
                        Screen.PaymentSuccess.createRoute(
                            amount = uiState.pendingPaymentAmount,
                            productName = uiState.pendingPaymentProductName,
                            skuText = uiState.pendingPaymentSkuText
                        )
                    )
                }
            }
        )
    }

    if (uiState.showSkuSheet) {
        SkuActionSheet(
            sheetState = skuSheetState,
            product = product,
            selectedSkuId = uiState.selectedSkuId,
            action = uiState.skuAction ?: SkuAction.AddToCart,
            isLoading = uiState.isCartActionLoading || uiState.showMockPaymentLoading,
            onDismiss = { viewModel.dismissSkuSheet() },
            onSelectSku = viewModel::selectSku,
            onConfirm = {
                when (uiState.skuAction) {
                    SkuAction.AddToCart -> viewModel.addToCart(
                        onSuccess = { Toast.makeText(context, "已加入购物车", Toast.LENGTH_SHORT).show() },
                        onError = { Toast.makeText(context, it, Toast.LENGTH_SHORT).show() }
                    )
                    SkuAction.BuyNow -> viewModel.buyNow {
                        Toast.makeText(context, it, Toast.LENGTH_SHORT).show()
                    }
                    null -> Unit
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

    Box(modifier = Modifier.fillMaxSize()) {
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
                        IconButton(onClick = { Toast.makeText(context, "分享功能开发中", Toast.LENGTH_SHORT).show() }) {
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
                ProductBottomBar(
                    isFavorited = uiState.isFavorited,
                    isFavoriteLoading = uiState.isFavoriteActionLoading,
                    isCartLoading = uiState.isCartActionLoading,
                    isPaymentLoading = uiState.showMockPaymentLoading,
                    onFavorite = {
                        viewModel.addFavorite(
                            onSuccess = { Toast.makeText(context, "已添加到我的收藏", Toast.LENGTH_SHORT).show() },
                            onError = { Toast.makeText(context, it, Toast.LENGTH_SHORT).show() }
                        )
                    },
                    onAddCart = {
                        viewModel.openSkuSheet(SkuAction.AddToCart)
                    },
                    onBuyNow = {
                        viewModel.openSkuSheet(SkuAction.BuyNow)
                    }
                )
            }
        ) { innerPadding ->
            Column(
                modifier = Modifier
                    .fillMaxSize()
                    .padding(innerPadding)
                    .verticalScroll(rememberScrollState())
            ) {
                ProductImageHeader(product = product, imageRequest = detailImageRequest)
                ProductInfoSection(
                    product = product,
                    onReviewsClick = {
                        navController.navigate(Screen.ProductReviews.createRoute(product.id))
                    }
                )
                ReviewPreviewSection(
                    reviews = product.reviews,
                    reviewCount = product.reviews.size.takeIf { it > 0 } ?: product.reviewCount,
                    onViewAll = {
                        navController.navigate(Screen.ProductReviews.createRoute(product.id))
                    }
                )
                SpecsSection(specs = product.specs)
                RelatedProductsSection(
                    relatedProducts = uiState.relatedProducts,
                    navController = navController
                )
                Spacer(modifier = Modifier.height(16.dp))
            }
        }

        if (uiState.showMockPaymentLoading) {
            Box(
                modifier = Modifier
                    .fillMaxSize()
                    .background(Color.Black.copy(alpha = 0.24f)),
                contentAlignment = Alignment.Center
            ) {
                MockWeChatLoadingDialog()
            }
        }
    }
}

@Composable
private fun ProductBottomBar(
    isFavorited: Boolean,
    isFavoriteLoading: Boolean,
    isCartLoading: Boolean,
    isPaymentLoading: Boolean,
    onFavorite: () -> Unit,
    onAddCart: () -> Unit,
    onBuyNow: () -> Unit
) {
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
            OutlinedButton(
                onClick = onFavorite,
                modifier = Modifier.weight(1f),
                enabled = !isFavoriteLoading
            ) {
                Icon(
                    imageVector = if (isFavorited) Icons.Default.Favorite else Icons.Default.FavoriteBorder,
                    contentDescription = null,
                    modifier = Modifier.height(18.dp)
                )
                Spacer(modifier = Modifier.width(4.dp))
                Text("收藏")
            }
            Button(
                onClick = onAddCart,
                modifier = Modifier.weight(1.45f),
                enabled = !isCartLoading && !isPaymentLoading,
                colors = ButtonDefaults.buttonColors(containerColor = MaterialTheme.colorScheme.primary)
            ) {
                Text(if (isCartLoading) "处理中" else "加入购物车")
            }
            Button(
                onClick = onBuyNow,
                modifier = Modifier.weight(1.45f),
                enabled = !isPaymentLoading,
                colors = ButtonDefaults.buttonColors(containerColor = PriceColor)
            ) {
                Text("立即购买")
            }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class, ExperimentalLayoutApi::class)
@Composable
private fun SkuActionSheet(
    sheetState: SheetState,
    product: Product,
    selectedSkuId: String?,
    action: SkuAction,
    isLoading: Boolean,
    onDismiss: () -> Unit,
    onSelectSku: (String) -> Unit,
    onConfirm: () -> Unit
) {
    val selectedSku = product.skus.firstOrNull { it.id == selectedSkuId }
    val actionText = when (action) {
        SkuAction.AddToCart -> "加入购物车"
        SkuAction.BuyNow -> "立即购买"
    }

    ModalBottomSheet(
        onDismissRequest = {
            if (!isLoading) onDismiss()
        },
        sheetState = sheetState
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 18.dp, vertical = 12.dp)
        ) {
            Text(
                text = "选择规格",
                style = MaterialTheme.typography.titleLarge,
                fontWeight = FontWeight.Bold
            )
            Spacer(modifier = Modifier.height(10.dp))
            Text(
                text = product.name,
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                maxLines = 2,
                overflow = TextOverflow.Ellipsis
            )
            Spacer(modifier = Modifier.height(14.dp))
            FlowRow(
                horizontalArrangement = Arrangement.spacedBy(8.dp),
                verticalArrangement = Arrangement.spacedBy(8.dp)
            ) {
                product.skus.forEach { sku ->
                    val selected = sku.id == selectedSkuId
                    OutlinedButton(
                        onClick = { onSelectSku(sku.id) },
                        enabled = sku.stock > 0 && !isLoading,
                        shape = RoundedCornerShape(10.dp),
                        colors = ButtonDefaults.outlinedButtonColors(
                            containerColor = if (selected) {
                                MaterialTheme.colorScheme.primaryContainer
                            } else {
                                MaterialTheme.colorScheme.surface
                            }
                        )
                    ) {
                        Column(horizontalAlignment = Alignment.Start) {
                            Text(
                                text = sku.skuText,
                                style = MaterialTheme.typography.labelLarge,
                                color = if (selected) {
                                    MaterialTheme.colorScheme.primary
                                } else {
                                    MaterialTheme.colorScheme.onSurface
                                }
                            )
                            Text(
                                text = "¥${"%.2f".format(sku.price)} · 库存 ${sku.stock}",
                                style = MaterialTheme.typography.bodySmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant
                            )
                        }
                    }
                }
            }
            Spacer(modifier = Modifier.height(16.dp))
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically
            ) {
                Column {
                    Text(
                        text = "SKU 价格",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant
                    )
                    Text(
                        text = selectedSku?.let { "¥${"%.2f".format(it.price)}" } ?: "请选择规格",
                        style = MaterialTheme.typography.titleMedium,
                        color = if (selectedSku == null) {
                            MaterialTheme.colorScheme.onSurfaceVariant
                        } else {
                            PriceColor
                        },
                        fontWeight = FontWeight.Bold
                    )
                }
                Button(
                    onClick = onConfirm,
                    enabled = !isLoading,
                    colors = ButtonDefaults.buttonColors(
                        containerColor = if (action == SkuAction.BuyNow) PriceColor else MaterialTheme.colorScheme.primary
                    )
                ) {
                    Text(if (isLoading) "处理中" else actionText)
                }
            }
            Spacer(modifier = Modifier.height(18.dp))
        }
    }
}

@Composable
private fun ProductImageHeader(product: Product, imageRequest: ImageRequest) {
    Box(
        modifier = Modifier
            .fillMaxWidth()
            .height(300.dp)
            .background(
                brush = Brush.linearGradient(
                    colors = listOf(Color(0xFFE8F0FE), Color(0xFFD2E3FC))
                )
            ),
        contentAlignment = Alignment.Center
    ) {
        AsyncImage(
            model = imageRequest,
            contentDescription = product.name,
            contentScale = ContentScale.Crop,
            modifier = Modifier.matchParentSize()
        )
        Box(
            modifier = Modifier
                .align(Alignment.TopStart)
                .padding(14.dp)
                .background(
                    color = MaterialTheme.colorScheme.primaryContainer.copy(alpha = 0.92f),
                    shape = RoundedCornerShape(8.dp)
                )
                .padding(horizontal = 10.dp, vertical = 4.dp)
        ) {
            Text(
                text = product.category,
                style = MaterialTheme.typography.labelMedium,
                color = MaterialTheme.colorScheme.primary
            )
        }
    }
}

@Composable
private fun ProductInfoSection(
    product: Product,
    onReviewsClick: () -> Unit
) {
    val displayPrice = product.price
    val displayOriginalPrice = product.originalPrice
    Column(modifier = Modifier.padding(16.dp)) {
        Row(
            verticalAlignment = Alignment.Bottom,
            horizontalArrangement = Arrangement.spacedBy(8.dp)
        ) {
            Text("¥", color = PriceColor, fontSize = 18.sp, fontWeight = FontWeight.Bold)
            Text(
                text = "%.0f".format(displayPrice),
                color = PriceColor,
                fontSize = 32.sp,
                fontWeight = FontWeight.Bold
            )
            displayOriginalPrice?.let { original ->
                Text(
                    text = "¥${"%.0f".format(original)}",
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
                        .background(Discount, RoundedCornerShape(4.dp))
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
        Text(
            text = product.name,
            style = MaterialTheme.typography.titleLarge,
            fontWeight = FontWeight.Bold,
            color = MaterialTheme.colorScheme.onSurface
        )
        Spacer(modifier = Modifier.height(8.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            SmallPill(product.brand)
            SmallPill(product.categoryId)
        }
        Spacer(modifier = Modifier.height(10.dp))
        Row(
            verticalAlignment = Alignment.CenterVertically,
            modifier = Modifier.clickable(onClick = onReviewsClick)
        ) {
            RatingBar(rating = product.rating, starSize = 18.dp)
            Spacer(modifier = Modifier.width(8.dp))
            Text(
                text = "%.1f".format(product.rating),
                style = MaterialTheme.typography.bodyMedium,
                fontWeight = FontWeight.SemiBold
            )
            Spacer(modifier = Modifier.width(10.dp))
            Text(
                text = "用户评价（${product.reviews.size.takeIf { it > 0 } ?: product.reviewCount}）",
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.primary
            )
            product.specs["销量"]?.let { sales ->
                Spacer(modifier = Modifier.width(10.dp))
                Text(
                    text = "销量 $sales",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
            }
        }
    }
}

@Composable
private fun SmallPill(text: String) {
    if (text.isBlank()) return
    Box(
        modifier = Modifier
            .background(MaterialTheme.colorScheme.primaryContainer, RoundedCornerShape(5.dp))
            .padding(horizontal = 8.dp, vertical = 3.dp)
    ) {
        Text(
            text = text,
            style = MaterialTheme.typography.labelMedium,
            color = MaterialTheme.colorScheme.primary
        )
    }
}

@Composable
private fun ProductIntroSection(product: Product) {
    DetailCard(title = "商品简介") {
        Text(
            text = product.description.compact(110),
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            lineHeight = 21.sp
        )
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun SkuSelectionSection(
    skus: List<ProductSku>,
    selectedSkuId: String?,
    onSelectSku: (String) -> Unit
) {
    if (skus.isEmpty()) return
    DetailCard(title = "选择规格") {
        FlowRow(
            horizontalArrangement = Arrangement.spacedBy(8.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp)
        ) {
            skus.forEach { sku ->
                val selected = sku.id == selectedSkuId
                OutlinedButton(
                    onClick = { onSelectSku(sku.id) },
                    enabled = sku.stock > 0,
                    shape = RoundedCornerShape(10.dp),
                    colors = ButtonDefaults.outlinedButtonColors(
                        containerColor = if (selected) {
                            MaterialTheme.colorScheme.primaryContainer
                        } else {
                            MaterialTheme.colorScheme.surface
                        }
                    )
                ) {
                    Column(horizontalAlignment = Alignment.Start) {
                        Text(
                            text = sku.skuText,
                            style = MaterialTheme.typography.labelLarge,
                            color = if (selected) {
                                MaterialTheme.colorScheme.primary
                            } else {
                                MaterialTheme.colorScheme.onSurface
                            }
                        )
                        Text(
                            text = "¥${"%.0f".format(sku.price)} · 库存 ${sku.stock}",
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant
                        )
                    }
                }
            }
        }
    }
}

@Composable
private fun AiCommentSection(comment: String) {
    if (comment.isBlank()) return
    DetailCard(title = "AI 智能点评", leadingIcon = true) {
        Text(
            text = comment.compact(120),
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurface,
            lineHeight = 21.sp
        )
    }
}

@Composable
private fun ReviewPreviewSection(
    reviews: List<ProductReview>,
    reviewCount: Int,
    onViewAll: () -> Unit
) {
    DetailCard(
        title = "用户评价（$reviewCount）",
        actionText = "查看全部评价",
        onActionClick = onViewAll
    ) {
        if (reviews.isEmpty()) {
            Text(
                text = "暂无评价",
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
        } else {
            Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                reviews.take(3).forEach { review ->
                    ReviewCard(review = review)
                }
            }
        }
    }
}

@Composable
private fun SpecsSection(specs: Map<String, String>) {
    if (specs.isEmpty()) return
    DetailCard(title = "规格参数") {
        specs.entries.forEachIndexed { index, (key, value) ->
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(vertical = 7.dp),
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
            if (index < specs.size - 1) {
                Divider(color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = 0.5f))
            }
        }
    }
}

@Composable
private fun RelatedProductsSection(
    relatedProducts: List<Product>,
    navController: NavHostController
) {
    if (relatedProducts.isEmpty()) return
    Column(modifier = Modifier.padding(vertical = 16.dp)) {
        Text(
            text = "相关推荐",
            style = MaterialTheme.typography.titleMedium,
            fontWeight = FontWeight.Bold,
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
                        navController.navigate(Screen.ProductDetail.createRoute(relatedProduct.id))
                    },
                    fixedWidth = 180.dp
                )
            }
        }
    }
}

@Composable
private fun DetailCard(
    title: String,
    leadingIcon: Boolean = false,
    actionText: String? = null,
    onActionClick: (() -> Unit)? = null,
    content: @Composable () -> Unit
) {
    Column(modifier = Modifier.padding(horizontal = 16.dp, vertical = 8.dp)) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            verticalAlignment = Alignment.CenterVertically
        ) {
            if (leadingIcon) {
                Icon(
                    imageVector = Icons.Default.Star,
                    contentDescription = null,
                    tint = MaterialTheme.colorScheme.primary,
                    modifier = Modifier.height(20.dp)
                )
                Spacer(modifier = Modifier.width(6.dp))
            }
            Text(
                text = title,
                style = MaterialTheme.typography.titleMedium,
                fontWeight = FontWeight.Bold,
                modifier = Modifier.weight(1f)
            )
            if (actionText != null && onActionClick != null) {
                Text(
                    text = actionText,
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.primary,
                    modifier = Modifier.clickable(onClick = onActionClick)
                )
            }
        }
        Spacer(modifier = Modifier.height(8.dp))
        Card(
            modifier = Modifier.fillMaxWidth(),
            shape = RoundedCornerShape(12.dp),
            colors = CardDefaults.cardColors(
                containerColor = MaterialTheme.colorScheme.surface
            ),
            elevation = CardDefaults.cardElevation(defaultElevation = 1.dp)
        ) {
            Column(modifier = Modifier.padding(14.dp)) {
                content()
            }
        }
    }
}

private fun String.compact(maxLength: Int): String {
    val text = trim().replace(Regex("\\s+"), " ")
    return if (text.length <= maxLength) text else "${text.take(maxLength).trimEnd()}..."
}
