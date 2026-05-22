package com.smartshop.ai.ui.components

import androidx.compose.animation.core.LinearEasing
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import com.smartshop.ai.ui.theme.SmartShopTheme

@Composable
fun ShimmerEffect(
    modifier: Modifier = Modifier,
    durationMillis: Int = 1200
) {
    val shimmerColors = listOf(
        Color(0xFFE8EAED),
        Color(0xFFF1F3F4),
        Color(0xFFE8EAED)
    )

    val transition = rememberInfiniteTransition(label = "shimmer")
    val translateAnim by transition.animateFloat(
        initialValue = 0f,
        targetValue = 1000f,
        animationSpec = infiniteRepeatable(
            animation = tween(durationMillis, easing = LinearEasing),
            repeatMode = RepeatMode.Restart
        ),
        label = "shimmer_translate"
    )

    val brush = Brush.linearGradient(
        colors = shimmerColors,
        start = Offset(translateAnim - 200f, translateAnim - 200f),
        end = Offset(translateAnim, translateAnim)
    )

    Box(
        modifier = modifier
            .clip(RoundedCornerShape(8.dp))
            .background(brush)
    )
}

@Composable
fun ShimmerProductCard(
    modifier: Modifier = Modifier
) {
    Column(
        modifier = modifier
            .width(180.dp)
            .clip(RoundedCornerShape(12.dp))
            .background(Color.White)
            .padding(0.dp)
    ) {
        // Image placeholder
        ShimmerEffect(
            modifier = Modifier
                .fillMaxWidth()
                .height(180.dp)
        )

        Column(modifier = Modifier.padding(10.dp)) {
            // Brand tag
            ShimmerEffect(
                modifier = Modifier
                    .width(40.dp)
                    .height(16.dp)
            )

            Spacer(modifier = Modifier.height(6.dp))

            // Title line 1
            ShimmerEffect(
                modifier = Modifier
                    .fillMaxWidth()
                    .height(14.dp)
            )

            Spacer(modifier = Modifier.height(4.dp))

            // Title line 2
            ShimmerEffect(
                modifier = Modifier
                    .width(120.dp)
                    .height(14.dp)
            )

            Spacer(modifier = Modifier.height(8.dp))

            // Rating
            ShimmerEffect(
                modifier = Modifier
                    .width(80.dp)
                    .height(12.dp)
            )

            Spacer(modifier = Modifier.height(8.dp))

            // Price
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                ShimmerEffect(
                    modifier = Modifier
                        .width(60.dp)
                        .height(20.dp)
                )
                ShimmerEffect(
                    modifier = Modifier
                        .width(40.dp)
                        .height(14.dp)
                )
            }
        }
    }
}

@Composable
fun ShimmerProductGrid(
    columns: Int = 2,
    rows: Int = 3,
    modifier: Modifier = Modifier
) {
    Column(
        modifier = modifier.padding(horizontal = 16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp)
    ) {
        repeat(rows) {
            Row(
                horizontalArrangement = Arrangement.spacedBy(12.dp),
                modifier = Modifier.fillMaxWidth()
            ) {
                repeat(columns) {
                    ShimmerProductCard(
                        modifier = Modifier.weight(1f)
                    )
                }
            }
        }
    }
}

@Preview(showBackground = true)
@Composable
private fun ShimmerProductCardPreview() {
    SmartShopTheme(dynamicColor = false) {
        ShimmerProductCard(modifier = Modifier.padding(16.dp))
    }
}

@Preview(showBackground = true)
@Composable
private fun ShimmerProductGridPreview() {
    SmartShopTheme(dynamicColor = false) {
        ShimmerProductGrid(modifier = Modifier.padding(vertical = 16.dp))
    }
}
