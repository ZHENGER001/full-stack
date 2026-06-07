package com.smartshop.ai.ui.cart

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.Button
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import androidx.navigation.NavHostController
import com.smartshop.ai.data.account.AccountRepository
import com.smartshop.ai.data.cart.CartRepository
import com.smartshop.ai.data.model.CartItem
import com.smartshop.ai.ui.navigation.Screen
import com.smartshop.ai.ui.payment.MockWeChatLoadingDialog
import com.smartshop.ai.ui.payment.MockWeChatPaymentSheet
import coil.compose.AsyncImage
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import javax.inject.Inject

data class CartUiState(
    val items: List<CartItem> = emptyList(),
    val isLoading: Boolean = false,
    val isCheckoutLoading: Boolean = false,
    val showMockPaymentLoading: Boolean = false,
    val showPaymentSheet: Boolean = false,
    val pendingOrderId: String? = null,
    val pendingPaymentAmount: Double = 0.0,
    val pendingPaymentProductName: String = "",
    val pendingPaymentSkuText: String = "",
    val paymentError: String? = null,
    val errorMessage: String? = null
) {
    val totalAmount: Double = items.filter { it.selected }.sumOf { it.price * it.quantity }
}

@HiltViewModel
class CartViewModel @Inject constructor(
    private val cartRepository: CartRepository,
    private val accountRepository: AccountRepository
) : ViewModel() {
    private val _uiState = MutableStateFlow(CartUiState(isLoading = true))
    val uiState: StateFlow<CartUiState> = _uiState.asStateFlow()

    fun load() {
        viewModelScope.launch {
            _uiState.value = CartUiState(isLoading = true)
            runCatching { cartRepository.getCart() }
                .onSuccess { _uiState.value = CartUiState(items = it) }
                .onFailure {
                    _uiState.value = CartUiState(
                        errorMessage = it.message ?: "购物车接口暂不可用"
                    )
                }
        }
    }

    fun clearCart() {
        if (_uiState.value.items.isEmpty()) return
        viewModelScope.launch {
            runCatching { cartRepository.clear() }
                .onSuccess {
                    _uiState.value = _uiState.value.copy(items = it, errorMessage = null)
                }
                .onFailure {
                    _uiState.value = _uiState.value.copy(
                        errorMessage = it.message ?: "清空购物车失败"
                    )
                }
        }
    }

    fun checkout() {
        val selectedItems = _uiState.value.items.filter { it.selected }
        if (
            selectedItems.isEmpty() ||
            _uiState.value.isCheckoutLoading ||
            _uiState.value.showMockPaymentLoading ||
            _uiState.value.showPaymentSheet
        ) return
        viewModelScope.launch {
            _uiState.value = _uiState.value.copy(
                showMockPaymentLoading = true,
                paymentError = null,
                errorMessage = null
            )
            delay(1200)
            runCatching { accountRepository.createOrderFromCart() }
                .onSuccess { order ->
                    _uiState.value = _uiState.value.copy(
                        showMockPaymentLoading = false,
                        showPaymentSheet = true,
                        pendingOrderId = order.id,
                        pendingPaymentAmount = order.totalAmount,
                        pendingPaymentProductName = selectedItems.paymentProductName(),
                        pendingPaymentSkuText = selectedItems.paymentSkuText()
                    )
                }
                .onFailure { error ->
                    _uiState.value = _uiState.value.copy(
                        showMockPaymentLoading = false,
                        errorMessage = error.message ?: "创建订单失败"
                    )
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
            isCheckoutLoading = false
        )
    }

    fun pay(password: String, onSuccess: (Double, String, String) -> Unit) {
        val orderId = _uiState.value.pendingOrderId ?: return
        val amount = _uiState.value.pendingPaymentAmount
        val productName = _uiState.value.pendingPaymentProductName
        val skuText = _uiState.value.pendingPaymentSkuText
        viewModelScope.launch {
            _uiState.value = _uiState.value.copy(isCheckoutLoading = true, paymentError = null)
            runCatching { accountRepository.payOrder(orderId, password) }
                .onSuccess {
                    dismissPayment()
                    onSuccess(amount, productName, skuText)
                }
                .onFailure { error ->
                    _uiState.value = _uiState.value.copy(
                        isCheckoutLoading = false,
                        paymentError = error.message ?: "支付失败"
                    )
                }
        }
    }

    private fun List<CartItem>.paymentProductName(): String =
        if (size == 1) {
            first().productName
        } else {
            "购物车订单（${sumOf { it.quantity }}件商品）"
        }

    private fun List<CartItem>.paymentSkuText(): String =
        if (size == 1) {
            first().skuText
        } else {
            take(2).joinToString("、") { it.skuText }
                .let { text -> if (size > 2) "$text 等 $size 种规格" else text }
        }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun CartScreen(
    navController: NavHostController,
    viewModel: CartViewModel = hiltViewModel()
) {
    val uiState by viewModel.uiState.collectAsState()
    val paymentSheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true)
    LaunchedEffect(Unit) {
        viewModel.load()
    }
    if (uiState.showPaymentSheet && uiState.pendingOrderId != null) {
        MockWeChatPaymentSheet(
            sheetState = paymentSheetState,
            productName = uiState.pendingPaymentProductName,
            skuText = uiState.pendingPaymentSkuText,
            amount = uiState.pendingPaymentAmount,
            isLoading = uiState.isCheckoutLoading,
            errorMessage = uiState.paymentError,
            onDismiss = { viewModel.dismissPayment() },
            onPasswordComplete = { password ->
                viewModel.pay(password) { amount, productName, skuText ->
                    navController.navigate(
                        Screen.PaymentSuccess.createRoute(
                            amount = amount,
                            productName = productName,
                            skuText = skuText
                        )
                    )
                }
            }
        )
    }

    Box(modifier = Modifier.fillMaxSize()) {
        Scaffold(
            topBar = {
                TopAppBar(
                    title = { Text("购物车") },
                    navigationIcon = {
                        IconButton(onClick = { navController.popBackStack() }) {
                            Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "返回")
                        }
                    },
                    actions = {
                        if (uiState.items.isNotEmpty()) {
                            TextButton(
                                onClick = { viewModel.clearCart() },
                                enabled = !uiState.isLoading && !uiState.isCheckoutLoading
                            ) {
                                Text("清空")
                            }
                        }
                    },
                    colors = TopAppBarDefaults.topAppBarColors(
                        containerColor = MaterialTheme.colorScheme.surface
                    )
                )
            }
        ) { paddingValues ->
            Column(
                modifier = Modifier
                    .fillMaxSize()
                    .padding(paddingValues)
                    .padding(16.dp)
            ) {
                when {
                    uiState.isLoading -> Text("正在加载购物车...")
                    uiState.errorMessage != null -> Text(uiState.errorMessage.orEmpty())
                    uiState.items.isEmpty() -> Text("购物车为空")
                    else -> {
                        LazyColumn(
                            modifier = Modifier.weight(1f),
                            verticalArrangement = Arrangement.spacedBy(10.dp)
                        ) {
                            items(uiState.items, key = { it.id }) { item ->
                                CartItemRow(item = item)
                            }
                        }
                        Spacer(modifier = Modifier.height(12.dp))
                        Text(
                            text = "合计：¥${"%.2f".format(uiState.totalAmount)}",
                            style = MaterialTheme.typography.titleMedium,
                            fontWeight = FontWeight.Bold,
                            color = MaterialTheme.colorScheme.primary
                        )
                        Spacer(modifier = Modifier.height(12.dp))
                        Button(
                            onClick = { viewModel.checkout() },
                            enabled = uiState.totalAmount > 0.0 &&
                                !uiState.isCheckoutLoading &&
                                !uiState.showMockPaymentLoading,
                            modifier = Modifier.fillMaxWidth()
                        ) {
                            Text(if (uiState.showMockPaymentLoading || uiState.isCheckoutLoading) "处理中..." else "微信支付")
                        }
                    }
                }
            }
        }

        if (uiState.showMockPaymentLoading) {
            Box(
                modifier = Modifier
                    .fillMaxSize()
                    .background(Color.Black.copy(alpha = 0.24f)),
                contentAlignment = androidx.compose.ui.Alignment.Center
            ) {
                MockWeChatLoadingDialog()
            }
        }
    }
}

@Composable
private fun CartItemRow(item: CartItem) {
    Card(
        modifier = Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface)
    ) {
        Row(modifier = Modifier.padding(12.dp)) {
            Box(
                modifier = Modifier
                    .size(72.dp)
                    .clip(RoundedCornerShape(8.dp))
                    .background(Color(0xFFF4F6F8))
            ) {
                AsyncImage(
                    model = item.productImage,
                    contentDescription = item.productName,
                    contentScale = ContentScale.Crop,
                    modifier = Modifier.fillMaxSize()
                )
            }
            Spacer(modifier = Modifier.width(12.dp))
            Column(modifier = Modifier.weight(1f)) {
                Text(
                    item.productName,
                    style = MaterialTheme.typography.bodyLarge,
                    fontWeight = FontWeight.SemiBold,
                    maxLines = 2
                )
                Spacer(modifier = Modifier.height(4.dp))
                Text(
                    "${item.brand} · ${item.skuText}",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
                Spacer(modifier = Modifier.height(8.dp))
                Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                    Text(
                        "¥${"%.2f".format(item.skuPrice)}",
                        color = MaterialTheme.colorScheme.primary,
                        fontWeight = FontWeight.Bold
                    )
                    Text("x${item.quantity}")
                }
            }
        }
    }
}
