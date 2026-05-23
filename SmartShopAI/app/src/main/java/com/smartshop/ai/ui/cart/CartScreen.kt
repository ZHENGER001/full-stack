package com.smartshop.ai.ui.cart

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
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
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import androidx.navigation.NavHostController
import com.smartshop.ai.data.account.AccountRepository
import com.smartshop.ai.data.cart.CartRepository
import com.smartshop.ai.data.model.CartItem
import com.smartshop.ai.ui.components.PaymentPasswordDialog
import com.smartshop.ai.ui.navigation.Screen
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import javax.inject.Inject

data class CartUiState(
    val items: List<CartItem> = emptyList(),
    val isLoading: Boolean = false,
    val isCheckoutLoading: Boolean = false,
    val pendingOrderId: String? = null,
    val pendingPaymentAmount: Double = 0.0,
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

    fun checkout() {
        if (_uiState.value.items.none { it.selected } || _uiState.value.isCheckoutLoading) return
        viewModelScope.launch {
            _uiState.value = _uiState.value.copy(isCheckoutLoading = true, paymentError = null)
            runCatching { accountRepository.createOrderFromCart() }
                .onSuccess { order ->
                    _uiState.value = _uiState.value.copy(
                        isCheckoutLoading = false,
                        pendingOrderId = order.id,
                        pendingPaymentAmount = order.totalAmount
                    )
                }
                .onFailure { error ->
                    _uiState.value = _uiState.value.copy(
                        isCheckoutLoading = false,
                        errorMessage = error.message ?: "创建订单失败"
                    )
                }
        }
    }

    fun dismissPayment() {
        _uiState.value = _uiState.value.copy(
            pendingOrderId = null,
            pendingPaymentAmount = 0.0,
            paymentError = null,
            isCheckoutLoading = false
        )
    }

    fun pay(password: String, onSuccess: () -> Unit) {
        val orderId = _uiState.value.pendingOrderId ?: return
        viewModelScope.launch {
            _uiState.value = _uiState.value.copy(isCheckoutLoading = true, paymentError = null)
            runCatching { accountRepository.payOrder(orderId, password) }
                .onSuccess {
                    dismissPayment()
                    onSuccess()
                }
                .onFailure { error ->
                    _uiState.value = _uiState.value.copy(
                        isCheckoutLoading = false,
                        paymentError = error.message ?: "支付失败"
                    )
                }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun CartScreen(
    navController: NavHostController,
    viewModel: CartViewModel = hiltViewModel()
) {
    val uiState by viewModel.uiState.collectAsState()
    LaunchedEffect(Unit) {
        viewModel.load()
    }
    if (uiState.pendingOrderId != null) {
        PaymentPasswordDialog(
            amount = uiState.pendingPaymentAmount,
            isLoading = uiState.isCheckoutLoading,
            errorMessage = uiState.paymentError,
            onDismiss = { viewModel.dismissPayment() },
            onConfirm = { password ->
                viewModel.pay(password) {
                    navController.navigate(Screen.Orders.route) {
                        popUpTo(Screen.Cart.route) { inclusive = true }
                    }
                }
            }
        )
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("购物车") },
                navigationIcon = {
                    IconButton(onClick = { navController.popBackStack() }) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "返回")
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
                        enabled = uiState.totalAmount > 0.0 && !uiState.isCheckoutLoading,
                        modifier = Modifier.fillMaxWidth()
                    ) {
                        Text(if (uiState.isCheckoutLoading) "处理中..." else "微信支付")
                    }
                }
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
        Column(modifier = Modifier.padding(12.dp)) {
            Text(item.title, style = MaterialTheme.typography.bodyLarge, fontWeight = FontWeight.SemiBold)
            Spacer(modifier = Modifier.height(4.dp))
            Text("${item.brand} · ${item.skuName}", style = MaterialTheme.typography.bodySmall)
            Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                Text("¥${"%.0f".format(item.price)}")
                Text("x${item.quantity}")
            }
        }
    }
}
