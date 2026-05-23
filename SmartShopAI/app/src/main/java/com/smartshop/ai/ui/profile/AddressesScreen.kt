package com.smartshop.ai.ui.profile

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
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Add
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.Checkbox
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import androidx.navigation.NavHostController
import com.smartshop.ai.data.account.AccountRepository
import com.smartshop.ai.data.model.ShippingAddress
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import javax.inject.Inject

data class AddressesUiState(
    val addresses: List<ShippingAddress> = emptyList(),
    val isLoading: Boolean = true,
    val isSaving: Boolean = false,
    val errorMessage: String? = null
)

@HiltViewModel
class AddressesViewModel @Inject constructor(
    private val accountRepository: AccountRepository
) : ViewModel() {
    private val _uiState = MutableStateFlow(AddressesUiState())
    val uiState: StateFlow<AddressesUiState> = _uiState.asStateFlow()

    fun load() {
        viewModelScope.launch {
            runCatching { accountRepository.getAddresses() }
                .onSuccess { _uiState.value = AddressesUiState(addresses = it, isLoading = false) }
                .onFailure { error ->
                    _uiState.value = AddressesUiState(
                        isLoading = false,
                        errorMessage = error.message ?: "地址接口暂不可用"
                    )
                }
        }
    }

    fun addAddress(
        receiverName: String,
        phone: String,
        province: String,
        city: String,
        district: String,
        detail: String,
        isDefault: Boolean
    ) {
        if (_uiState.value.isSaving) return
        viewModelScope.launch {
            _uiState.value = _uiState.value.copy(isSaving = true, errorMessage = null)
            runCatching {
                accountRepository.addAddress(receiverName, phone, province, city, district, detail, isDefault)
            }.onSuccess {
                load()
            }.onFailure { error ->
                _uiState.value = _uiState.value.copy(
                    isSaving = false,
                    errorMessage = error.message ?: "保存地址失败"
                )
            }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun AddressesScreen(
    navController: NavHostController,
    viewModel: AddressesViewModel = hiltViewModel()
) {
    val uiState by viewModel.uiState.collectAsState()
    var showForm by remember { mutableStateOf(false) }
    LaunchedEffect(Unit) {
        viewModel.load()
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("我的地址") },
                navigationIcon = {
                    IconButton(onClick = { navController.popBackStack() }) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "返回")
                    }
                },
                actions = {
                    IconButton(onClick = { showForm = !showForm }) {
                        Icon(Icons.Default.Add, contentDescription = "添加地址")
                    }
                },
                colors = TopAppBarDefaults.topAppBarColors(containerColor = MaterialTheme.colorScheme.surface)
            )
        }
    ) { innerPadding ->
        LazyColumn(
            modifier = Modifier
                .fillMaxSize()
                .padding(innerPadding),
            contentPadding = PaddingValues(16.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp)
        ) {
            if (showForm) {
                item {
                    AddressForm(
                        isSaving = uiState.isSaving,
                        onSave = { receiver, phone, province, city, district, detail, isDefault ->
                            viewModel.addAddress(receiver, phone, province, city, district, detail, isDefault)
                            showForm = false
                        }
                    )
                }
            }
            if (uiState.errorMessage != null) {
                item {
                    Text(uiState.errorMessage.orEmpty(), color = MaterialTheme.colorScheme.error)
                }
            }
            if (uiState.isLoading) {
                item {
                    Box(modifier = Modifier.fillMaxWidth(), contentAlignment = Alignment.Center) {
                        Text("正在加载地址...")
                    }
                }
            } else if (uiState.addresses.isEmpty()) {
                item {
                    Text("暂无地址，点击右上角添加")
                }
            } else {
                items(uiState.addresses, key = { it.id }) { address ->
                    AddressCard(address)
                }
            }
        }
    }
}

@Composable
private fun AddressForm(
    isSaving: Boolean,
    onSave: (String, String, String, String, String, String, Boolean) -> Unit
) {
    var receiver by remember { mutableStateOf("") }
    var phone by remember { mutableStateOf("") }
    var province by remember { mutableStateOf("广东省") }
    var city by remember { mutableStateOf("深圳市") }
    var district by remember { mutableStateOf("南山区") }
    var detail by remember { mutableStateOf("") }
    var isDefault by remember { mutableStateOf(true) }

    Card(shape = RoundedCornerShape(10.dp)) {
        Column(modifier = Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            OutlinedTextField(receiver, { receiver = it }, label = { Text("收货人") }, modifier = Modifier.fillMaxWidth())
            OutlinedTextField(phone, { phone = it }, label = { Text("手机号") }, modifier = Modifier.fillMaxWidth())
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedTextField(province, { province = it }, label = { Text("省") }, modifier = Modifier.weight(1f))
                OutlinedTextField(city, { city = it }, label = { Text("市") }, modifier = Modifier.weight(1f))
            }
            OutlinedTextField(district, { district = it }, label = { Text("区") }, modifier = Modifier.fillMaxWidth())
            OutlinedTextField(detail, { detail = it }, label = { Text("详细地址") }, modifier = Modifier.fillMaxWidth())
            Row(verticalAlignment = Alignment.CenterVertically) {
                Checkbox(checked = isDefault, onCheckedChange = { isDefault = it })
                Text("设为默认地址")
            }
            Button(
                onClick = { onSave(receiver, phone, province, city, district, detail, isDefault) },
                enabled = !isSaving && receiver.isNotBlank() && phone.isNotBlank() && detail.isNotBlank(),
                modifier = Modifier.fillMaxWidth()
            ) {
                Text(if (isSaving) "保存中..." else "保存地址")
            }
        }
    }
}

@Composable
private fun AddressCard(address: ShippingAddress) {
    Card(
        modifier = Modifier.fillMaxWidth(),
        shape = RoundedCornerShape(10.dp),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface)
    ) {
        Column(modifier = Modifier.padding(14.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(address.receiverName, fontWeight = FontWeight.Bold)
                Spacer(modifier = Modifier.height(0.dp).weight(1f))
                if (address.isDefault) {
                    Text("默认", color = MaterialTheme.colorScheme.primary, style = MaterialTheme.typography.labelMedium)
                }
            }
            Spacer(modifier = Modifier.height(4.dp))
            Text(address.phone, style = MaterialTheme.typography.bodySmall)
            Text(address.fullText, style = MaterialTheme.typography.bodyMedium)
        }
    }
}
