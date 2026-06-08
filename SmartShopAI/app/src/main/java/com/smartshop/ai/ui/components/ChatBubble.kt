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
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.AddShoppingCart
import androidx.compose.material.icons.filled.ShoppingCart
import androidx.compose.material.icons.filled.SmartToy
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
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
import com.smartshop.ai.data.model.CartItem
import com.smartshop.ai.data.model.ChatAction
import com.smartshop.ai.data.model.ChatMessage
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
    onActionClick: (ChatAction) -> Unit = {},
    onOpenCart: () -> Unit = {}
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

                            if (message.isLoading && message.content.isBlank()) {
                                Text(
                                    text = "正在思考...",
                                    color = if (isUser) UserBubbleText else AiBubbleText,
                                    style = MaterialTheme.typography.bodyMedium
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

                            if (!isUser && message.productRecommendations.isNotEmpty()) {
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
                    Text(
                        text = formatTimestamp(message.timestamp),
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.6f),
                        modifier = Modifier.padding(horizontal = 4.dp)
                    )

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
    val reason = product.aiComment
        .takeIf { it.isUserFacingRecommendationReason() }
        ?.toCompleteReason(maxLength = 86)
    return when (index) {
        0 -> RecommendationGroup(
            icon = "🔥",
            title = "优先推荐款",
            description = reason ?: "这款${category}匹配度较高，价格、评分和库存表现更稳，可以优先看看。"
        )
        1 -> RecommendationGroup(
            icon = "🏃",
            title = "功能实用款",
            description = reason ?: "${name.compactName()}更适合日常使用或明确场景需求，综合表现比较均衡。"
        )
        else -> RecommendationGroup(
            icon = "💰",
            title = "平价备选款",
            description = reason ?: "如果想多一个备选方向，这款${category}可以作为价格和实用性之间的折中选择。"
        )
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
    if (isBlank()) return false
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
