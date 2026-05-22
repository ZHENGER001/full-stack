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
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import com.smartshop.ai.data.model.Banner
import com.smartshop.ai.ui.theme.SmartShopTheme
import kotlinx.coroutines.delay

@Composable
fun BannerCarousel(
    banners: List<Banner>,
    modifier: Modifier = Modifier,
    autoScrollDelay: Long = 4000L,
    onBannerClick: (Banner) -> Unit = {}
) {
    if (banners.isEmpty()) return

    val listState = rememberLazyListState()
    var currentIndex by remember { mutableIntStateOf(0) }

    // Auto-scroll effect
    LaunchedEffect(banners.size) {
        if (banners.size > 1) {
            while (true) {
                delay(autoScrollDelay)
                currentIndex = (currentIndex + 1) % banners.size
                listState.animateScrollToItem(currentIndex)
            }
        }
    }

    Column(modifier = modifier) {
        LazyRow(
            state = listState,
            contentPadding = PaddingValues(horizontal = 16.dp),
            horizontalArrangement = Arrangement.spacedBy(12.dp),
            modifier = Modifier.fillMaxWidth()
        ) {
            items(banners, key = { it.id }) { banner ->
                BannerItem(
                    banner = banner,
                    onClick = { onBannerClick(banner) },
                    modifier = Modifier.fillParentMaxWidth(0.92f)
                )
            }
        }

        // Page indicator dots
        if (banners.size > 1) {
            Spacer(modifier = Modifier.height(10.dp))
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.Center
            ) {
                banners.forEachIndexed { index, _ ->
                    val isActive = index == currentIndex
                    Box(
                        modifier = Modifier
                            .padding(horizontal = 3.dp)
                            .size(if (isActive) 8.dp else 6.dp)
                            .clip(CircleShape)
                            .background(
                                if (isActive) MaterialTheme.colorScheme.primary
                                else MaterialTheme.colorScheme.outline.copy(alpha = 0.4f)
                            )
                    )
                }
            }
        }
    }
}

@Composable
private fun BannerItem(
    banner: Banner,
    onClick: () -> Unit,
    modifier: Modifier = Modifier
) {
    Card(
        modifier = modifier
            .height(160.dp)
            .clickable { onClick() },
        shape = RoundedCornerShape(16.dp),
        elevation = CardDefaults.cardElevation(defaultElevation = 4.dp)
    ) {
        Box(
            modifier = Modifier
                .fillMaxSize()
                .background(Color(banner.backgroundColor))
        ) {
            // Gradient overlay for text readability
            Box(
                modifier = Modifier
                    .fillMaxSize()
                    .background(
                        brush = Brush.horizontalGradient(
                            colors = listOf(
                                Color.Black.copy(alpha = 0.4f),
                                Color.Transparent
                            )
                        )
                    )
            )

            // Decorative circles
            Box(
                modifier = Modifier
                    .align(Alignment.TopEnd)
                    .padding(top = 12.dp, end = 24.dp)
                    .size(80.dp)
                    .clip(CircleShape)
                    .background(Color.White.copy(alpha = 0.1f))
            )
            Box(
                modifier = Modifier
                    .align(Alignment.BottomEnd)
                    .padding(bottom = 20.dp, end = 60.dp)
                    .size(50.dp)
                    .clip(CircleShape)
                    .background(Color.White.copy(alpha = 0.08f))
            )

            // Text content
            Column(
                modifier = Modifier
                    .align(Alignment.CenterStart)
                    .padding(start = 24.dp, end = 100.dp)
            ) {
                Text(
                    text = banner.title,
                    style = MaterialTheme.typography.titleLarge,
                    fontWeight = FontWeight.Bold,
                    color = Color.White,
                    maxLines = 2
                )
                Spacer(modifier = Modifier.height(4.dp))
                Text(
                    text = banner.subtitle,
                    style = MaterialTheme.typography.bodyMedium,
                    color = Color.White.copy(alpha = 0.85f),
                    maxLines = 2
                )
            }
        }
    }
}

@Preview(showBackground = true)
@Composable
private fun BannerCarouselPreview() {
    SmartShopTheme(dynamicColor = false) {
        BannerCarousel(
            banners = listOf(
                Banner(
                    id = "1",
                    title = "618大促来袭",
                    subtitle = "全场低至5折起",
                    imageUrl = "",
                    backgroundColor = 0xFF1A73E8
                ),
                Banner(
                    id = "2",
                    title = "新品首发",
                    subtitle = "AI精选好物推荐",
                    imageUrl = "",
                    backgroundColor = 0xFF34A853
                ),
                Banner(
                    id = "3",
                    title = "限时特惠",
                    subtitle = "数码产品专场",
                    imageUrl = "",
                    backgroundColor = 0xFFFF6B35
                )
            ),
            modifier = Modifier.padding(vertical = 16.dp)
        )
    }
}
