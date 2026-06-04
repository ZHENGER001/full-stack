package com.smartshop.ai.ui.components

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
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
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.AddShoppingCart
import androidx.compose.material.icons.filled.SmartToy
import androidx.compose.material3.AssistChip
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextDecoration
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import coil.compose.AsyncImage
import com.smartshop.ai.data.model.ChatAction
import com.smartshop.ai.data.model.ChatMessage
import com.smartshop.ai.data.model.Product
import com.smartshop.ai.ui.theme.AiBubble
import com.smartshop.ai.ui.theme.AiBubbleText
import com.smartshop.ai.ui.theme.PriceColor
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
    onActionClick: (ChatAction) -> Unit = {}
) {
    val isUser = message.isUser
    val alignment = if (isUser) Alignment.CenterEnd else Alignment.CenterStart

    Box(
        modifier = modifier
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
                if (message.productRecommendations.isNotEmpty()) {
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

                if (message.actions.isNotEmpty()) {
                    Spacer(modifier = Modifier.height(8.dp))
                    LazyRow(
                        contentPadding = PaddingValues(end = 8.dp),
                        horizontalArrangement = Arrangement.spacedBy(8.dp)
                    ) {
                        items(message.actions) { action ->
                            AssistChip(
                                onClick = { onActionClick(action) },
                                label = {
                                    Text(
                                        text = action.label,
                                        style = MaterialTheme.typography.labelSmall
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

@Composable
private fun MiniProductCard(
    product: Product,
    onClick: () -> Unit,
    onAddToCart: () -> Unit,
    modifier: Modifier = Modifier
) {
    Card(
        modifier = modifier
            .clickable { onClick() },
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
                        contentPadding = PaddingValues(horizontal = 0.dp, vertical = 0.dp)
                    ) {
                        Icon(
                            imageVector = Icons.Default.AddShoppingCart,
                            contentDescription = null,
                            tint = MaterialTheme.colorScheme.primary,
                            modifier = Modifier.size(15.dp)
                        )
                    }
                }
            }
        }
    }
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
