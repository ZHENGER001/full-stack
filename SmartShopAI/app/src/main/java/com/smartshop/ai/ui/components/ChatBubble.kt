package com.smartshop.ai.ui.components

import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.animateContentSize
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.slideInVertically
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.interaction.collectIsPressedAsState
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
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.VolumeUp
import androidx.compose.material.icons.filled.AddShoppingCart
import androidx.compose.material.icons.filled.ShoppingCart
import androidx.compose.material.icons.filled.SmartToy
import androidx.compose.material.icons.filled.Stop
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateMapOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextDecoration
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import coil.compose.AsyncImage
import com.smartshop.ai.data.model.BatchCartContent
import com.smartshop.ai.data.model.BatchCartItem
import com.smartshop.ai.data.model.BatchCartSku
import com.smartshop.ai.data.model.CartItem
import com.smartshop.ai.data.model.ChatAction
import com.smartshop.ai.data.model.ChatMessage
import com.smartshop.ai.data.model.ComparisonContent
import com.smartshop.ai.data.model.Product
import com.smartshop.ai.ui.theme.AiBubble
import com.smartshop.ai.ui.theme.AiBubbleText
import com.smartshop.ai.ui.theme.PriceColor
import com.smartshop.ai.ui.theme.Primary
import com.smartshop.ai.ui.theme.PrimaryLight
import com.smartshop.ai.ui.theme.SmartShopTheme
import com.smartshop.ai.ui.theme.UserBubble
import com.smartshop.ai.ui.theme.UserBubbleText
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

@Composable
fun ChatBubble(
    message: ChatMessage,
    modifier: Modifier = Modifier,
    onProductClick: (String) -> Unit = {},
    onAddToCart: (String) -> Unit = {},
    onBatchCartConfirm: (BatchCartContent, Map<String, String>) -> Unit = { _, _ -> },
    onActionClick: (ChatAction) -> Unit = {},
    onOpenCart: () -> Unit = {},
    onSpeak: (ChatMessage) -> Unit = {},
    onStopSpeaking: () -> Unit = {},
    isSpeaking: Boolean = false
) {
    val isUser = message.isUser
    val alignment = if (isUser) Alignment.CenterEnd else Alignment.CenterStart
    val followUpActions = message.actions.filter {
        it.type == "search_more" && it.label.isContextualFollowUp()
    }
    var entered by remember(message.id) { mutableStateOf(false) }

    LaunchedEffect(message.id) {
        entered = true
    }

    AnimatedVisibility(
        visible = entered,
        enter = fadeIn(animationSpec = tween(180)) + slideInVertically(
            animationSpec = tween(220),
            initialOffsetY = { it / 8 }
        ),
        exit = fadeOut(animationSpec = tween(120)),
        modifier = modifier.fillMaxWidth()
    ) {
        Box(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 12.dp, vertical = 4.dp),
            contentAlignment = alignment
        ) {
            Row(
                verticalAlignment = Alignment.Top,
                horizontalArrangement = if (isUser) Arrangement.End else Arrangement.Start
            ) {
                // AI avatar
                if (!isUser) {
                    Box(
                        modifier = Modifier
                            .size(32.dp)
                            .clip(CircleShape)
                            .background(MaterialTheme.colorScheme.primary),
                        contentAlignment = Alignment.Center
                    ) {
                        Icon(
                            imageVector = Icons.Default.SmartToy,
                            contentDescription = "AI",
                            tint = Color.White,
                            modifier = Modifier.size(20.dp)
                        )
                    }
                    Spacer(modifier = Modifier.width(8.dp))
                }

                Column(
                    horizontalAlignment = if (isUser) Alignment.End else Alignment.Start,
                    modifier = if (isUser) Modifier.widthIn(max = 280.dp) else Modifier.weight(1f)
                ) {
                    // Message bubble
                    Box(
                        modifier = Modifier
                            .animateContentSize(animationSpec = tween(180))
                            .background(
                                color = if (isUser) UserBubble else AiBubble,
                                shape = RoundedCornerShape(
                                    topStart = 16.dp,
                                    topEnd = 16.dp,
                                    bottomStart = if (isUser) 16.dp else 4.dp,
                                    bottomEnd = if (isUser) 4.dp else 16.dp
                                )
                            )
                            .padding(horizontal = 14.dp, vertical = 10.dp)
                    ) {
                        Column {
                            message.imageUri?.let { imageUri ->
                                AsyncImage(
                                    model = imageUri,
                                    contentDescription = "用户图片",
                                    modifier = Modifier
                                        .fillMaxWidth()
                                        .height(160.dp)
                                        .clip(RoundedCornerShape(12.dp))
                                )
                                Spacer(modifier = Modifier.height(8.dp))
                            }

                            val comparison = if (!isUser) message.comparison else null
                            if (message.isLoading && message.content.isBlank() && comparison == null) {
                                Text(
                                    text = "正在思考...",
                                    color = if (isUser) UserBubbleText else AiBubbleText,
                                    style = MaterialTheme.typography.bodyMedium
                                )
                            } else if (comparison != null) {
                                ComparisonPanel(
                                    comparison = comparison,
                                    products = message.productRecommendations.take(3),
                                    onProductClick = onProductClick
                                )
                            } else {
                                Text(
                                    text = message.content,
                                    color = if (isUser) UserBubbleText else AiBubbleText,
                                    style = MaterialTheme.typography.bodyMedium,
                                    lineHeight = 22.sp
                                )
                            }

                            if (!isUser && !message.orderStatusText.isNullOrBlank()) {
                                Spacer(modifier = Modifier.height(10.dp))
                                OrderStatusPill(text = message.orderStatusText)
                            }

                            if (!isUser && message.batchCart != null) {
                                Spacer(modifier = Modifier.height(14.dp))
                                BatchCartSelectionCard(
                                    batchCart = message.batchCart,
                                    onConfirm = onBatchCartConfirm
                                )
                            }

                            if (!isUser && message.productRecommendations.isNotEmpty() && comparison == null) {
                                Spacer(modifier = Modifier.height(14.dp))
                                InlineRecommendationList(
                                    products = message.productRecommendations.take(3),
                                    onProductClick = onProductClick
                                )
                            }

                            if (!isUser && message.cartItems.isNotEmpty()) {
                                Spacer(modifier = Modifier.height(14.dp))
                                CartSummaryCard(
                                    items = message.cartItems,
                                    totalAmount = message.cartTotalAmount ?: message.cartItems.sumOf { it.skuPrice * it.quantity },
                                    onProductClick = onProductClick,
                                    onOpenCart = onOpenCart
                                )
                            }
                        }
                    }

                    // Timestamp
                    Spacer(modifier = Modifier.height(2.dp))
                    Row(
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = if (isUser) Arrangement.End else Arrangement.Start
                    ) {
                        Text(
                            text = formatTimestamp(message.timestamp),
                            style = MaterialTheme.typography.labelSmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.6f),
                            modifier = Modifier.padding(horizontal = 4.dp)
                        )
                        if (!isUser && message.content.isNotBlank()) {
                            IconButton(
                                onClick = {
                                    if (isSpeaking) onStopSpeaking() else onSpeak(message)
                                },
                                modifier = Modifier.size(32.dp)
                            ) {
                                Icon(
                                    imageVector = if (isSpeaking) {
                                        Icons.Default.Stop
                                    } else {
                                        Icons.AutoMirrored.Filled.VolumeUp
                                    },
                                    contentDescription = if (isSpeaking) "停止朗读" else "朗读回复",
                                    tint = MaterialTheme.colorScheme.primary,
                                    modifier = Modifier.size(18.dp)
                                )
                            }
                        }
                    }

                    // Product recommendations
                    if (isUser && message.productRecommendations.isNotEmpty()) {
                        Spacer(modifier = Modifier.height(8.dp))
                        Row(
                            modifier = Modifier.fillMaxWidth(),
                            horizontalArrangement = Arrangement.spacedBy(8.dp)
                        ) {
                            message.productRecommendations.take(3).forEach { product ->
                                MiniProductCard(
                                    product = product,
                                    onClick = { onProductClick(product.id) },
                                    onAddToCart = { onAddToCart(product.id) },
                                    modifier = Modifier.weight(1f)
                                )
                            }
                        }
                    }

                    if (followUpActions.isNotEmpty()) {
                        Spacer(modifier = Modifier.height(10.dp))
                        FollowUpQuestionList(
                            actions = followUpActions,
                            onActionClick = onActionClick
                        )
                    }
                }
            }
        }
    }
}

@Composable
private fun OrderStatusPill(text: String) {
    Box(
        modifier = Modifier
            .animateContentSize(animationSpec = tween(180))
            .background(
                color = PrimaryLight,
                shape = RoundedCornerShape(999.dp)
            )
            .border(
                width = 1.dp,
                color = Primary.copy(alpha = 0.25f),
                shape = RoundedCornerShape(999.dp)
            )
            .padding(horizontal = 10.dp, vertical = 5.dp)
    ) {
        Text(
            text = text,
            style = MaterialTheme.typography.labelMedium,
            color = Primary,
            fontWeight = FontWeight.Medium
        )
    }
}

@Composable
private fun BatchCartSelectionCard(
    batchCart: BatchCartContent,
    onConfirm: (BatchCartContent, Map<String, String>) -> Unit
) {
    val selectedSkuIds = remember(batchCart.batchId) {
        mutableStateMapOf<String, String>().apply {
            batchCart.items.forEach { item ->
                val selected = item.selectedSkuId ?: item.skus.singleOrNull()?.skuId
                if (!selected.isNullOrBlank()) put(item.productId, selected)
            }
        }
    }
    var submitted by remember(batchCart.batchId) { mutableStateOf(false) }
    val selectedCount = batchCart.items.count { selectedSkuIds[it.productId] != null }
    val ready = selectedCount == batchCart.items.size && batchCart.items.isNotEmpty()

    Column(
        modifier = Modifier
            .fillMaxWidth()
            .animateContentSize(animationSpec = tween(180))
            .background(
                color = MaterialTheme.colorScheme.surface,
                shape = RoundedCornerShape(12.dp)
            )
            .border(
                width = 1.dp,
                color = MaterialTheme.colorScheme.outline.copy(alpha = 0.42f),
                shape = RoundedCornerShape(12.dp)
            )
            .padding(12.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp)
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Icon(
                imageVector = Icons.Default.AddShoppingCart,
                contentDescription = null,
                tint = Primary,
                modifier = Modifier.size(20.dp)
            )
            Spacer(modifier = Modifier.width(8.dp))
            Column(modifier = Modifier.weight(1f)) {
                Text(
                    text = batchCart.title.ifBlank { "批量加入购物车" },
                    style = MaterialTheme.typography.titleSmall,
                    fontWeight = FontWeight.Bold,
                    color = AiBubbleText
                )
                Text(
                    text = "已选择 $selectedCount / ${batchCart.items.size} 个商品规格",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
            }
            BatchCartProgressPill(ready = ready)
        }

        batchCart.items.forEach { item ->
            BatchCartItemRow(
                item = item,
                selectedSkuId = selectedSkuIds[item.productId],
                onSelectSku = { skuId ->
                    selectedSkuIds[item.productId] = skuId
                    submitted = false
                }
            )
        }

        val buttonColor = if (ready && !submitted) Primary else MaterialTheme.colorScheme.surfaceVariant
        val textColor = if (ready && !submitted) Color.White else MaterialTheme.colorScheme.onSurfaceVariant
        Box(
            modifier = Modifier
                .fillMaxWidth()
                .clip(RoundedCornerShape(10.dp))
                .background(buttonColor)
                .clickable(enabled = ready && !submitted) {
                    submitted = true
                    onConfirm(batchCart, selectedSkuIds.toMap())
                }
                .padding(vertical = 12.dp),
            contentAlignment = Alignment.Center
        ) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Icon(
                    imageVector = Icons.Default.AddShoppingCart,
                    contentDescription = null,
                    tint = textColor,
                    modifier = Modifier.size(18.dp)
                )
                Spacer(modifier = Modifier.width(7.dp))
                Text(
                    text = when {
                        submitted -> "已提交"
                        ready -> "确认加入购物车"
                        else -> "请先选完规格"
                    },
                    style = MaterialTheme.typography.labelLarge,
                    fontWeight = FontWeight.Bold,
                    color = textColor
                )
            }
        }
    }
}

@Composable
private fun BatchCartProgressPill(ready: Boolean) {
    val text = if (ready) "可确认" else "待选择"
    val color = if (ready) Primary else MaterialTheme.colorScheme.tertiary
    Box(
        modifier = Modifier
            .background(color.copy(alpha = 0.12f), RoundedCornerShape(999.dp))
            .border(1.dp, color.copy(alpha = 0.26f), RoundedCornerShape(999.dp))
            .padding(horizontal = 9.dp, vertical = 4.dp)
    ) {
        Text(
            text = text,
            style = MaterialTheme.typography.labelSmall,
            color = color,
            fontWeight = FontWeight.SemiBold
        )
    }
}

@Composable
private fun BatchCartItemRow(
    item: BatchCartItem,
    selectedSkuId: String?,
    onSelectSku: (String) -> Unit
) {
    val selectedSku = item.skus.firstOrNull { it.skuId == selectedSkuId }
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .background(MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.38f), RoundedCornerShape(10.dp))
            .padding(10.dp),
        verticalArrangement = Arrangement.spacedBy(9.dp)
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            AsyncImage(
                model = item.imageUrl,
                contentDescription = item.title,
                contentScale = ContentScale.Crop,
                modifier = Modifier
                    .size(54.dp)
                    .clip(RoundedCornerShape(8.dp))
                    .background(MaterialTheme.colorScheme.surfaceVariant)
            )
            Spacer(modifier = Modifier.width(10.dp))
            Column(modifier = Modifier.weight(1f)) {
                Text(
                    text = item.title,
                    style = MaterialTheme.typography.bodyMedium,
                    color = AiBubbleText,
                    fontWeight = FontWeight.SemiBold,
                    maxLines = 2,
                    overflow = TextOverflow.Ellipsis
                )
                Spacer(modifier = Modifier.height(3.dp))
                Text(
                    text = "${item.brand} · ¥${"%.2f".format(item.price)}",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis
                )
            }
            BatchCartSkuStatus(label = selectedSku?.label)
        }

        if (item.skus.isEmpty()) {
            Text(
                text = "暂无可购买规格",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.error
            )
        } else {
            Row(
                modifier = Modifier.horizontalScroll(rememberScrollState()),
                horizontalArrangement = Arrangement.spacedBy(8.dp)
            ) {
                item.skus.forEach { sku ->
                    BatchCartSkuChip(
                        sku = sku,
                        selected = sku.skuId == selectedSkuId,
                        onClick = { onSelectSku(sku.skuId) }
                    )
                }
            }
        }
    }
}

@Composable
private fun BatchCartSkuStatus(label: String?) {
    val selected = !label.isNullOrBlank()
    val color = if (selected) Primary else MaterialTheme.colorScheme.error
    Box(
        modifier = Modifier
            .background(color.copy(alpha = 0.10f), RoundedCornerShape(999.dp))
            .padding(horizontal = 8.dp, vertical = 4.dp)
    ) {
        Text(
            text = if (selected) "已选 $label" else "待选",
            style = MaterialTheme.typography.labelSmall,
            color = color,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis
        )
    }
}

@Composable
private fun BatchCartSkuChip(
    sku: BatchCartSku,
    selected: Boolean,
    onClick: () -> Unit
) {
    val bg = if (selected) Primary else MaterialTheme.colorScheme.surface
    val fg = if (selected) Color.White else AiBubbleText
    val border = if (selected) Primary else MaterialTheme.colorScheme.outline.copy(alpha = 0.45f)
    Column(
        modifier = Modifier
            .widthIn(min = 86.dp, max = 150.dp)
            .clip(RoundedCornerShape(9.dp))
            .background(bg)
            .border(1.dp, border, RoundedCornerShape(9.dp))
            .clickable(onClick = onClick)
            .padding(horizontal = 10.dp, vertical = 8.dp)
    ) {
        Text(
            text = sku.label,
            style = MaterialTheme.typography.labelMedium,
            color = fg,
            fontWeight = FontWeight.SemiBold,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis
        )
        Text(
            text = "¥${"%.0f".format(sku.price)} · 库存${sku.stock}",
            style = MaterialTheme.typography.labelSmall,
            color = fg.copy(alpha = 0.78f),
            maxLines = 1,
            overflow = TextOverflow.Ellipsis
        )
    }
}

@Composable
private fun ComparisonPanel(
    comparison: ComparisonContent,
    products: List<Product>,
    onProductClick: (String) -> Unit
) {
    Column(
        modifier = Modifier.fillMaxWidth(),
        verticalArrangement = Arrangement.spacedBy(12.dp)
    ) {
        Text(
            text = comparison.title,
            style = MaterialTheme.typography.titleLarge,
            color = AiBubbleText,
            fontWeight = FontWeight.Bold,
            lineHeight = 27.sp
        )
        Text(
            text = comparison.summary,
            style = MaterialTheme.typography.bodyMedium,
            color = AiBubbleText,
            lineHeight = 22.sp
        )
        Text(
            text = "核心差异一览",
            style = MaterialTheme.typography.titleMedium,
            color = AiBubbleText,
            fontWeight = FontWeight.Bold
        )
        ComparisonTable(comparison)
        ComparisonSections(comparison)
        if (products.isNotEmpty()) {
            ComparisonProductStrip(
                products = products,
                onProductClick = onProductClick
            )
        }
        Box(
            modifier = Modifier
                .fillMaxWidth()
                .background(
                    color = PrimaryLight.copy(alpha = 0.55f),
                    shape = RoundedCornerShape(10.dp)
                )
                .border(
                    width = 1.dp,
                    color = Primary.copy(alpha = 0.22f),
                    shape = RoundedCornerShape(10.dp)
                )
                .padding(10.dp)
        ) {
            Text(
                text = comparison.recommendation,
                style = MaterialTheme.typography.bodyMedium,
                color = AiBubbleText,
                lineHeight = 22.sp,
                fontWeight = FontWeight.SemiBold
            )
        }
        comparison.footnote?.takeIf { it.isNotBlank() }?.let { footnote ->
            Text(
                text = footnote,
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                lineHeight = 16.sp
            )
        }
    }
}

@Composable
private fun ComparisonTable(comparison: ComparisonContent) {
    val columns = comparison.columns.take(3)
    val rows = comparison.rows.filter { row ->
        row.dimension.isNotBlank() && row.values.isNotEmpty()
    }
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(8.dp))
            .background(Color.White)
            .border(
                width = 1.dp,
                color = MaterialTheme.colorScheme.outline.copy(alpha = 0.16f),
                shape = RoundedCornerShape(8.dp)
            )
    ) {
        Box(
            modifier = Modifier
                .fillMaxWidth()
                .height(4.dp)
                .background(Primary)
        )
        Row(modifier = Modifier.fillMaxWidth()) {
            ComparisonCell(
                text = "维度",
                isHeader = true,
                modifier = Modifier.weight(0.85f)
            )
            columns.forEach { column ->
                ComparisonCell(
                    text = column.label,
                    isHeader = true,
                    modifier = Modifier.weight(1f)
                )
            }
        }
        rows.forEach { row ->
            Row(modifier = Modifier.fillMaxWidth()) {
                ComparisonCell(
                    text = row.dimension,
                    modifier = Modifier.weight(0.85f)
                )
                columns.forEachIndexed { index, _ ->
                    ComparisonCell(
                        text = row.values.getOrNull(index).orEmpty(),
                        highlighted = row.highlightIndex == index,
                        modifier = Modifier.weight(1f)
                    )
                }
            }
        }
    }
}

@Composable
private fun ComparisonCell(
    text: String,
    modifier: Modifier = Modifier,
    isHeader: Boolean = false,
    highlighted: Boolean = false
) {
    Box(
        modifier = modifier
            .height(74.dp)
            .border(
                width = 0.5.dp,
                color = MaterialTheme.colorScheme.outline.copy(alpha = 0.13f)
            )
            .background(
                color = when {
                    isHeader -> MaterialTheme.colorScheme.surface
                    highlighted -> PrimaryLight.copy(alpha = 0.38f)
                    else -> Color.White
                }
            )
            .padding(horizontal = 8.dp, vertical = 9.dp),
        contentAlignment = Alignment.CenterStart
    ) {
        Text(
            text = text.ifBlank { "暂无" },
            style = if (isHeader) MaterialTheme.typography.labelLarge else MaterialTheme.typography.bodySmall,
            color = AiBubbleText,
            fontWeight = if (isHeader || highlighted) FontWeight.Bold else FontWeight.Normal,
            lineHeight = 17.sp,
            maxLines = 3,
            overflow = TextOverflow.Ellipsis
        )
    }
}

@Composable
private fun ComparisonSections(comparison: ComparisonContent) {
    val sections = comparison.sections.filter { it.bullets.isNotEmpty() }.take(3)
    if (sections.isEmpty()) return
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Text(
            text = "怎么选不吃亏",
            style = MaterialTheme.typography.titleMedium,
            color = AiBubbleText,
            fontWeight = FontWeight.Bold
        )
        sections.forEach { section ->
            Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                Text(
                    text = section.title,
                    style = MaterialTheme.typography.bodyMedium,
                    color = AiBubbleText,
                    fontWeight = FontWeight.Bold
                )
                section.bullets.take(3).forEach { bullet ->
                    Text(
                        text = "· $bullet",
                        style = MaterialTheme.typography.bodyMedium,
                        color = AiBubbleText,
                        lineHeight = 22.sp
                    )
                }
            }
        }
    }
}

@Composable
private fun ComparisonProductStrip(
    products: List<Product>,
    onProductClick: (String) -> Unit
) {
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Text(
            text = "对应商品",
            style = MaterialTheme.typography.titleMedium,
            color = AiBubbleText,
            fontWeight = FontWeight.Bold
        )
        products.take(2).forEach { product ->
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .clip(RoundedCornerShape(8.dp))
                    .background(Color.White)
                    .clickable { onProductClick(product.id) }
                    .padding(8.dp),
                verticalAlignment = Alignment.CenterVertically
            ) {
                AsyncImage(
                    model = product.imageUrl,
                    contentDescription = product.name,
                    modifier = Modifier
                        .size(58.dp)
                        .clip(RoundedCornerShape(8.dp)),
                    contentScale = ContentScale.Crop
                )
                Spacer(modifier = Modifier.width(10.dp))
                Column(modifier = Modifier.weight(1f)) {
                    Text(
                        text = product.name,
                        style = MaterialTheme.typography.bodyMedium,
                        color = AiBubbleText,
                        fontWeight = FontWeight.Bold,
                        maxLines = 2,
                        overflow = TextOverflow.Ellipsis
                    )
                    Spacer(modifier = Modifier.height(3.dp))
                    Text(
                        text = "¥${"%.2f".format(product.price)} · ${product.brand} · ${product.category.ifBlank { "商品" }}",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis
                    )
                }
            }
        }
    }
}

@Composable
private fun MiniProductCard(
    product: Product,
    onClick: () -> Unit,
    onAddToCart: () -> Unit,
    modifier: Modifier = Modifier
) {
    val cardInteraction = remember { MutableInteractionSource() }
    val cartInteraction = remember { MutableInteractionSource() }
    val cardPressed by cardInteraction.collectIsPressedAsState()
    val cartPressed by cartInteraction.collectIsPressedAsState()
    val cardScale by animateFloatAsState(
        targetValue = if (cardPressed) 0.98f else 1f,
        animationSpec = tween(140),
        label = "miniProductCardScale"
    )
    val cartScale by animateFloatAsState(
        targetValue = if (cartPressed) 0.86f else 1f,
        animationSpec = tween(140),
        label = "miniCartScale"
    )

    Card(
        modifier = modifier
            .graphicsLayer {
                scaleX = cardScale
                scaleY = cardScale
            }
            .animateContentSize(animationSpec = tween(180))
            .clickable(
                interactionSource = cardInteraction,
                indication = null,
                onClick = onClick
            ),
        shape = RoundedCornerShape(8.dp),
        elevation = CardDefaults.cardElevation(defaultElevation = 2.dp),
        colors = CardDefaults.cardColors(
            containerColor = MaterialTheme.colorScheme.surface
        )
    ) {
        Column {
            Box(
                modifier = Modifier
                    .fillMaxWidth()
                    .height(96.dp),
                contentAlignment = Alignment.Center
            ) {
                AsyncImage(
                    model = product.imageUrl,
                    contentDescription = product.name,
                    contentScale = ContentScale.Crop,
                    modifier = Modifier.fillMaxSize()
                )
            }

            Column(modifier = Modifier.padding(horizontal = 6.dp, vertical = 5.dp)) {
                Text(
                    text = product.name,
                    style = MaterialTheme.typography.labelSmall,
                    maxLines = 2,
                    overflow = TextOverflow.Ellipsis,
                    fontWeight = FontWeight.Medium
                )
                Spacer(modifier = Modifier.height(3.dp))
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text(
                        text = "¥${"%.0f".format(product.price)}",
                        color = PriceColor,
                        fontSize = 15.sp,
                        fontWeight = FontWeight.Bold
                    )
                    Spacer(modifier = Modifier.width(4.dp))
                    Text(
                        text = "★${"%.1f".format(product.rating)}",
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        maxLines = 1
                    )
                }
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.SpaceBetween,
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    TextButton(
                        onClick = onClick,
                        modifier = Modifier.weight(1f),
                        contentPadding = PaddingValues(horizontal = 0.dp, vertical = 0.dp)
                    ) {
                        Text(text = "详情", style = MaterialTheme.typography.labelSmall)
                    }
                    TextButton(
                        onClick = onAddToCart,
                        modifier = Modifier.weight(1f),
                        interactionSource = cartInteraction,
                        contentPadding = PaddingValues(horizontal = 0.dp, vertical = 0.dp)
                    ) {
                        Icon(
                            imageVector = Icons.Default.AddShoppingCart,
                            contentDescription = null,
                            tint = MaterialTheme.colorScheme.primary,
                            modifier = Modifier
                                .size(15.dp)
                                .graphicsLayer {
                                    scaleX = cartScale
                                    scaleY = cartScale
                                }
                        )
                    }
                }
            }
        }
    }
}

@Composable
private fun FollowUpQuestionList(
    actions: List<ChatAction>,
    onActionClick: (ChatAction) -> Unit
) {
    Column(
        verticalArrangement = Arrangement.spacedBy(9.dp),
        horizontalAlignment = Alignment.Start
    ) {
        actions.take(3).forEach { action ->
            val interactionSource = remember(action.label) { MutableInteractionSource() }
            val pressed by interactionSource.collectIsPressedAsState()
            val scale by animateFloatAsState(
                targetValue = if (pressed) 0.97f else 1f,
                animationSpec = tween(140),
                label = "followUpScale"
            )

            Box(
                modifier = Modifier
                    .widthIn(min = 176.dp, max = 320.dp)
                    .graphicsLayer {
                        scaleX = scale
                        scaleY = scale
                    }
                    .animateContentSize(animationSpec = tween(180))
                    .background(
                        color = PrimaryLight,
                        shape = RoundedCornerShape(14.dp)
                    )
                    .border(
                        width = 1.dp,
                        color = Primary.copy(alpha = 0.35f),
                        shape = RoundedCornerShape(14.dp)
                    )
                    .clickable(
                        interactionSource = interactionSource,
                        indication = null,
                        onClick = { onActionClick(action) }
                    )
                    .padding(horizontal = 16.dp, vertical = 11.dp)
            ) {
                Text(
                    text = action.label,
                    style = MaterialTheme.typography.bodyMedium,
                    fontWeight = FontWeight.Medium,
                    color = Primary,
                    maxLines = 2,
                    overflow = TextOverflow.Ellipsis
                )
            }
        }
    }
}

@Composable
private fun InlineRecommendationList(
    products: List<Product>,
    onProductClick: (String) -> Unit
) {
    Column(verticalArrangement = Arrangement.spacedBy(16.dp)) {
        products.forEachIndexed { index, product ->
            InlineRecommendationItem(
                product = product,
                group = recommendationGroup(index, product),
                onClick = { onProductClick(product.id) }
            )
        }
    }
}

@Composable
private fun CartSummaryCard(
    items: List<CartItem>,
    totalAmount: Double,
    onProductClick: (String) -> Unit,
    onOpenCart: () -> Unit
) {
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .animateContentSize(animationSpec = tween(180))
            .background(
                color = MaterialTheme.colorScheme.surface,
                shape = RoundedCornerShape(12.dp)
            )
            .border(
                width = 1.dp,
                color = MaterialTheme.colorScheme.outline.copy(alpha = 0.45f),
                shape = RoundedCornerShape(12.dp)
            )
            .padding(12.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp)
    ) {
        Text(
            text = "购物车详情",
            style = MaterialTheme.typography.titleSmall,
            fontWeight = FontWeight.Bold,
            color = AiBubbleText
        )
        items.take(3).forEach { item ->
            CartSummaryItem(
                item = item,
                onProductClick = { onProductClick(item.productId) }
            )
        }
        Row(
            modifier = Modifier.fillMaxWidth(),
            verticalAlignment = Alignment.CenterVertically
        ) {
            Text(
                text = "合计 ¥${"%.2f".format(totalAmount)}",
                modifier = Modifier.weight(1f),
                style = MaterialTheme.typography.bodyMedium,
                fontWeight = FontWeight.Bold,
                color = PriceColor
            )
            TextButton(
                onClick = onOpenCart,
                contentPadding = PaddingValues(horizontal = 10.dp, vertical = 4.dp)
            ) {
                Icon(
                    imageVector = Icons.Default.ShoppingCart,
                    contentDescription = null,
                    modifier = Modifier.size(16.dp)
                )
                Spacer(modifier = Modifier.width(4.dp))
                Text(text = "打开购物车", style = MaterialTheme.typography.labelMedium)
            }
        }
    }
}

@Composable
private fun CartSummaryItem(
    item: CartItem,
    onProductClick: () -> Unit
) {
    val interactionSource = remember { MutableInteractionSource() }
    val pressed by interactionSource.collectIsPressedAsState()
    val scale by animateFloatAsState(
        targetValue = if (pressed) 0.96f else 1f,
        animationSpec = tween(140),
        label = "cartSummaryImageScale"
    )

    Row(
        modifier = Modifier.fillMaxWidth(),
        verticalAlignment = Alignment.CenterVertically
    ) {
        AsyncImage(
            model = item.productImage,
            contentDescription = item.productName,
            contentScale = ContentScale.Crop,
            modifier = Modifier
                .size(58.dp)
                .graphicsLayer {
                    scaleX = scale
                    scaleY = scale
                }
                .clip(RoundedCornerShape(8.dp))
                .background(MaterialTheme.colorScheme.surfaceVariant)
                .clickable(
                    interactionSource = interactionSource,
                    indication = null,
                    onClick = onProductClick
                )
        )
        Spacer(modifier = Modifier.width(10.dp))
        Column(modifier = Modifier.weight(1f)) {
            Text(
                text = item.productName,
                style = MaterialTheme.typography.bodyMedium,
                fontWeight = FontWeight.SemiBold,
                color = AiBubbleText,
                maxLines = 2,
                overflow = TextOverflow.Ellipsis
            )
            Spacer(modifier = Modifier.height(3.dp))
            Text(
                text = "${item.brand} · ${item.skuText} · x${item.quantity}",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis
            )
            Spacer(modifier = Modifier.height(3.dp))
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(
                    text = "¥${"%.2f".format(item.skuPrice)}",
                    style = MaterialTheme.typography.bodySmall,
                    fontWeight = FontWeight.Bold,
                    color = PriceColor
                )
                Spacer(modifier = Modifier.width(10.dp))
                Text(
                    text = "详情",
                    modifier = Modifier.clickable(onClick = onProductClick),
                    style = MaterialTheme.typography.labelMedium,
                    color = Primary
                )
            }
        }
    }
}

@Composable
private fun InlineRecommendationItem(
    product: Product,
    group: RecommendationGroup,
    onClick: () -> Unit
) {
    Column {
        Text(
            text = "${group.icon} ${group.title}",
            style = MaterialTheme.typography.titleSmall,
            fontWeight = FontWeight.Bold,
            color = AiBubbleText
        )
        Spacer(modifier = Modifier.height(6.dp))
        Text(
            text = group.description,
            style = MaterialTheme.typography.bodyMedium,
            color = AiBubbleText,
            lineHeight = 21.sp
        )
        Spacer(modifier = Modifier.height(10.dp))
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .clickable(onClick = onClick),
            verticalAlignment = Alignment.CenterVertically
        ) {
            AsyncImage(
                model = product.imageUrl,
                contentDescription = product.name,
                contentScale = ContentScale.Crop,
                modifier = Modifier
                    .size(74.dp)
                    .clip(RoundedCornerShape(8.dp))
                    .background(MaterialTheme.colorScheme.surfaceVariant)
            )
            Spacer(modifier = Modifier.width(12.dp))
            Column(modifier = Modifier.weight(1f)) {
                Text(
                    text = product.name,
                    style = MaterialTheme.typography.bodyMedium,
                    fontWeight = FontWeight.SemiBold,
                    color = AiBubbleText,
                    maxLines = 2,
                    overflow = TextOverflow.Ellipsis
                )
                Spacer(modifier = Modifier.height(5.dp))
                Text(
                    text = "¥${"%.2f".format(product.price)} · ${product.brand} · ${product.category.ifBlank { "商品" }}",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis
                )
            }
        }
    }
}

private data class RecommendationGroup(
    val icon: String,
    val title: String,
    val description: String
)

private fun recommendationGroup(index: Int, product: Product): RecommendationGroup {
    val name = product.name
    val category = product.category.ifBlank { product.categoryId }.ifBlank { "商品" }
    val title = product.recommendationTitle
        .takeIf { it.isNotBlank() }
        ?: fallbackRecommendationTitle(index)
    val reason = product.aiComment
        .takeIf { it.isUserFacingRecommendationReason() }
        ?.toCompleteReason(maxLength = 86)
    return RecommendationGroup(
        icon = recommendationIcon(title),
        title = title,
        description = reason ?: fallbackRecommendationDescription(index, name, category)
    )
}

private fun fallbackRecommendationTitle(index: Int): String =
    when (index) {
        0 -> "综合匹配"
        1 -> "功能匹配"
        else -> "备选款"
    }

private fun fallbackRecommendationDescription(index: Int, name: String, category: String): String =
    when (index) {
        0 -> "这款${category}匹配当前需求，可以优先看看。"
        1 -> "${name.compactName()}和你的需求有明确关联，适合作为功能侧重点的选择。"
        else -> "这款${category}可以作为另一个备选方向，适合和前面商品一起对比。"
    }

private fun recommendationIcon(title: String): String {
    return when {
        title.contains("防晒") || title.contains("防护") || title.contains("海边") -> "☀️"
        title.contains("拍照") || title.contains("影像") || title.contains("摄影") -> "📷"
        title.contains("续航") -> "🔋"
        title.contains("性能") || title.contains("游戏") || title.contains("配置") -> "⚡"
        title.contains("降噪") || title.contains("耳机") || title.contains("音质") || title.contains("通勤") -> "🎧"
        title.contains("价格") || title.contains("预算") || title.contains("性价比") || title.contains("平价") -> "💰"
        title.contains("评分") || title.contains("口碑") -> "⭐"
        title.contains("鞋") || title.contains("运动") || title.contains("实战") -> "🏃"
        title.contains("包") || title.contains("收纳") || title.contains("背包") -> "🎒"
        title.contains("护理") || title.contains("修复") || title.contains("补水") -> "💧"
        title.contains("搭配") || title.contains("套装") || title.contains("组合") -> "🧩"
        title.contains("优先") || title.contains("综合") -> "🔥"
        title.contains("功能") || title.contains("实用") -> "✅"
        else -> "🔎"
    }
}

private fun String.compactName(): String =
    if (length <= 18) this else take(18).trimEnd() + "..."

private fun String.toCompleteReason(maxLength: Int): String {
    val text = trim().replace(Regex("\\s+"), " ")
    if (text.length <= maxLength) return text
    val boundary = listOf("。", "！", "？", "；", "，", ",")
        .map { text.lastIndexOf(it, startIndex = maxLength.coerceAtMost(text.lastIndex)) }
        .filter { it in 32 until maxLength }
        .maxOrNull()
    return if (boundary != null) {
        val sentence = text.take(boundary + 1).trim()
        if (sentence.last() in listOf('，', ',')) sentence.dropLast(1) + "。" else sentence
    } else {
        text.take(maxLength).trimEnd('，', ',', '。', ' ') + "。"
    }
}

private fun String.isUserFacingRecommendationReason(): Boolean {
    if (isBlank() || trim().equals("null", ignoreCase = true)) return false
    val technicalTokens = listOf("Matched by", "retrieval", "RRF", "bm25", "dense", "keyword", "score")
    return technicalTokens.none { contains(it, ignoreCase = true) }
}

private fun String.isContextualFollowUp(): Boolean {
    val text = trim()
    if (text.isBlank()) return false
    val genericLabels = setOf("换一批", "查看更多", "换个关键词再搜")
    return text !in genericLabels
}

private fun formatTimestamp(timestamp: Long): String {
    val sdf = SimpleDateFormat("HH:mm", Locale.getDefault())
    return sdf.format(Date(timestamp))
}

@Preview(showBackground = true, backgroundColor = 0xFFF8F9FA)
@Composable
private fun ChatBubbleUserPreview() {
    SmartShopTheme(dynamicColor = false) {
        Column {
            ChatBubble(
                message = ChatMessage(
                    content = "帮我推荐一款拍照好的手机，预算3000左右",
                    isUser = true
                )
            )
            ChatBubble(
                message = ChatMessage(
                    content = "根据您的需求，我为您推荐以下几款拍照表现出色且在3000元价位的手机：",
                    isUser = false,
                    productRecommendations = listOf(
                        Product(
                            id = "1",
                            name = "Xiaomi 14",
                            description = "",
                            price = 2999.0,
                            originalPrice = 3299.0,
                            imageUrl = "",
                            category = "手机",
                            categoryId = "phone",
                            brand = "小米",
                            rating = 4.7f,
                            reviewCount = 8800
                        ),
                        Product(
                            id = "2",
                            name = "OPPO Reno11 Pro",
                            description = "",
                            price = 2799.0,
                            originalPrice = 3199.0,
                            imageUrl = "",
                            category = "手机",
                            categoryId = "phone",
                            brand = "OPPO",
                            rating = 4.6f,
                            reviewCount = 5200
                        )
                    )
                )
            )
        }
    }
}
