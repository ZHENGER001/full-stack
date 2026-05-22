package com.smartshop.ai.ui.components

import androidx.compose.foundation.layout.Row
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.TextUnit
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.smartshop.ai.ui.theme.SmartShopTheme
import com.smartshop.ai.ui.theme.Warning

@Composable
fun RatingBar(
    rating: Float,
    modifier: Modifier = Modifier,
    maxStars: Int = 5,
    starSize: Dp = 16.dp,
    activeColor: Color = Warning,
    inactiveColor: Color = Color(0xFFDADCE0)
) {
    val fontSize: TextUnit = (starSize.value).sp

    Row(modifier = modifier) {
        for (i in 1..maxStars) {
            val star = when {
                rating >= i -> "★"       // filled star
                rating >= i - 0.5f -> "★" // half star (render as filled for simplicity, color adjusted)
                else -> "☆"               // empty star
            }
            val color = when {
                rating >= i -> activeColor
                rating >= i - 0.5f -> activeColor.copy(alpha = 0.6f)
                else -> inactiveColor
            }
            Text(
                text = star,
                fontSize = fontSize,
                color = color
            )
        }
    }
}

@Preview(showBackground = true)
@Composable
private fun RatingBarPreview() {
    SmartShopTheme(dynamicColor = false) {
        RatingBar(rating = 4.5f)
    }
}
