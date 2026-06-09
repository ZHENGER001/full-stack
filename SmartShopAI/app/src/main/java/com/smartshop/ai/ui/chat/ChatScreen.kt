package com.smartshop.ai.ui.chat

import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeIn
import androidx.compose.animation.slideInVertically
import androidx.activity.result.contract.ActivityResultContracts
import androidx.activity.compose.rememberLauncherForActivityResult
import android.Manifest
import android.app.Activity
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.speech.RecognizerIntent
import android.speech.tts.TextToSpeech
import android.speech.tts.UtteranceProgressListener
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.ArrowUpward
import androidx.compose.material.icons.filled.Image
import androidx.compose.material.icons.filled.Mic
import androidx.compose.material.icons.filled.PhotoCamera
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.SuggestionChip
import androidx.compose.material3.SuggestionChipDefaults
import androidx.compose.material3.Text
import androidx.compose.material3.TextField
import androidx.compose.material3.TextFieldDefaults
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.core.content.FileProvider
import androidx.core.content.ContextCompat
import androidx.navigation.NavController
import com.smartshop.ai.data.mock.MockData
import com.smartshop.ai.ui.components.ChatBubble
import com.smartshop.ai.ui.navigation.Screen
import com.smartshop.ai.ui.theme.Primary
import java.io.File
import java.util.Locale
import kotlinx.coroutines.launch

private const val TTS_UTTERANCE_PREFIX = "smartshop_tts_"

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ChatScreen(
    navController: NavController,
    viewModel: ChatViewModel = hiltViewModel()
) {
    val messages by viewModel.messages.collectAsState()
    val inputText by viewModel.inputText.collectAsState()
    val isTyping by viewModel.isTyping.collectAsState()
    val listState = rememberLazyListState()
    val snackbarHostState = remember { SnackbarHostState() }
    val context = LocalContext.current
    val coroutineScope = rememberCoroutineScope()
    val mainHandler = remember { Handler(Looper.getMainLooper()) }
    var pendingCameraUri by remember { mutableStateOf<Uri?>(null) }
    var isListening by remember { mutableStateOf(false) }
    var textToSpeech by remember { mutableStateOf<TextToSpeech?>(null) }
    var isTtsReady by remember { mutableStateOf(false) }
    var speakingMessageId by remember { mutableStateOf<String?>(null) }
    var shouldAutoSpeakVoiceReply by remember { mutableStateOf(false) }
    var voiceRequestStartedAt by remember { mutableStateOf<Long?>(null) }

    DisposableEffect(context) {
        var ttsRef: TextToSpeech? = null
        val tts = TextToSpeech(context.applicationContext) { status ->
            mainHandler.post {
                if (status == TextToSpeech.SUCCESS) {
                    ttsRef?.setLanguage(Locale.getDefault())
                    isTtsReady = true
                } else {
                    isTtsReady = false
                }
            }
        }
        ttsRef = tts
        tts.setOnUtteranceProgressListener(object : UtteranceProgressListener() {
            override fun onStart(utteranceId: String?) = Unit

            override fun onDone(utteranceId: String?) {
                clearSpeakingState(utteranceId)
            }

            @Deprecated("Deprecated in Java")
            override fun onError(utteranceId: String?) {
                clearSpeakingState(utteranceId)
            }

            override fun onError(utteranceId: String?, errorCode: Int) {
                clearSpeakingState(utteranceId)
            }

            private fun clearSpeakingState(utteranceId: String?) {
                val messageId = utteranceId?.removePrefix(TTS_UTTERANCE_PREFIX)
                mainHandler.post {
                    if (speakingMessageId == messageId) {
                        speakingMessageId = null
                    }
                }
            }
        })
        textToSpeech = tts

        onDispose {
            tts.stop()
            tts.shutdown()
            textToSpeech = null
            isTtsReady = false
            speakingMessageId = null
        }
    }

    fun speakAssistantMessage(messageId: String, content: String) {
        val text = content.trim()
        if (text.isBlank()) return
        val tts = textToSpeech
        if (tts == null || !isTtsReady) {
            coroutineScope.launch { snackbarHostState.showSnackbar("语音朗读初始化中，请稍后再试") }
            return
        }
        if (speakingMessageId == messageId) {
            tts.stop()
            speakingMessageId = null
            return
        }

        tts.stop()
        speakingMessageId = messageId
        val result = tts.speak(
            text,
            TextToSpeech.QUEUE_FLUSH,
            Bundle.EMPTY,
            "$TTS_UTTERANCE_PREFIX$messageId"
        )
        if (result == TextToSpeech.ERROR) {
            speakingMessageId = null
            coroutineScope.launch { snackbarHostState.showSnackbar("语音朗读失败，请稍后再试") }
        }
    }

    fun stopAssistantSpeech() {
        textToSpeech?.stop()
        speakingMessageId = null
    }

    val imagePickerLauncher = rememberLauncherForActivityResult(
        contract = ActivityResultContracts.GetContent()
    ) { uri ->
        uri?.let { viewModel.sendMessage(imageUri = it) }
    }
    val cameraLauncher = rememberLauncherForActivityResult(
        contract = ActivityResultContracts.TakePicture()
    ) { success ->
        if (success) {
            pendingCameraUri?.let { viewModel.sendMessage(imageUri = it) }
        }
    }
    val speechLauncher = rememberLauncherForActivityResult(
        contract = ActivityResultContracts.StartActivityForResult()
    ) { result ->
        isListening = false
        if (result.resultCode == Activity.RESULT_OK) {
            val spokenText = result.data
                ?.getStringArrayListExtra(RecognizerIntent.EXTRA_RESULTS)
                ?.firstOrNull()
                .orEmpty()
            if (spokenText.isBlank()) {
                coroutineScope.launch { snackbarHostState.showSnackbar("没有识别到语音，请再试一次") }
            } else {
                stopAssistantSpeech()
                voiceRequestStartedAt = System.currentTimeMillis()
                shouldAutoSpeakVoiceReply = true
                viewModel.sendMessage(spokenText)
            }
        } else {
            coroutineScope.launch { snackbarHostState.showSnackbar("语音识别失败，请重新输入") }
        }
    }
    fun startVoiceRecognition() {
        val intent = Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH).apply {
            putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
            putExtra(RecognizerIntent.EXTRA_LANGUAGE, Locale.getDefault())
            putExtra(RecognizerIntent.EXTRA_PROMPT, "请说出你的购物需求")
        }
        isListening = true
        coroutineScope.launch { snackbarHostState.showSnackbar("正在识别语音...") }
        runCatching { speechLauncher.launch(intent) }
            .onFailure {
                isListening = false
                coroutineScope.launch { snackbarHostState.showSnackbar("语音识别失败，请重新输入") }
            }
    }
    val audioPermissionLauncher = rememberLauncherForActivityResult(
        contract = ActivityResultContracts.RequestPermission()
    ) { granted ->
        if (granted) {
            startVoiceRecognition()
        } else {
            coroutineScope.launch { snackbarHostState.showSnackbar("需要麦克风权限才能使用语音输入") }
        }
    }

    // Auto-scroll to bottom when messages change
    LaunchedEffect(messages.size, isTyping) {
        if (messages.isNotEmpty()) {
            // Scroll to index 0 because the list is reversed
            listState.animateScrollToItem(0)
        }
    }

    LaunchedEffect(messages, isTyping, isTtsReady, shouldAutoSpeakVoiceReply, voiceRequestStartedAt) {
        if (!shouldAutoSpeakVoiceReply || isTyping || !isTtsReady) return@LaunchedEffect

        val startedAt = voiceRequestStartedAt ?: return@LaunchedEffect
        val assistantReply = messages.lastOrNull { message ->
            !message.isUser &&
                !message.isLoading &&
                message.content.isNotBlank() &&
                message.timestamp >= startedAt
        } ?: return@LaunchedEffect

        shouldAutoSpeakVoiceReply = false
        voiceRequestStartedAt = null
        speakAssistantMessage(assistantReply.id, assistantReply.content)
    }

    LaunchedEffect(Unit) {
        viewModel.events.collect { message ->
            snackbarHostState.showSnackbar(message)
        }
    }

    Scaffold(
        snackbarHost = { SnackbarHost(snackbarHostState) },
        topBar = {
            TopAppBar(
                title = {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Box(
                            modifier = Modifier
                                .size(32.dp)
                                .clip(CircleShape)
                                .background(Primary),
                            contentAlignment = Alignment.Center
                        ) {
                            Text(
                                text = "AI",
                                color = Color.White,
                                fontSize = 12.sp,
                                fontWeight = FontWeight.Bold
                            )
                        }
                        Spacer(modifier = Modifier.width(10.dp))
                        Column {
                            Text(
                                text = "AI智能导购",
                                style = MaterialTheme.typography.titleMedium,
                                fontWeight = FontWeight.SemiBold
                            )
                            Text(
                                text = if (isTyping) "正在输入..." else "在线",
                                style = MaterialTheme.typography.labelSmall,
                                color = if (isTyping) Primary else MaterialTheme.colorScheme.onSurfaceVariant
                            )
                        }
                    }
                },
                navigationIcon = {
                    IconButton(onClick = { navController.popBackStack() }) {
                        Icon(
                            imageVector = Icons.AutoMirrored.Filled.ArrowBack,
                            contentDescription = "返回"
                        )
                    }
                },
                colors = TopAppBarDefaults.topAppBarColors(
                    containerColor = MaterialTheme.colorScheme.surface
                )
            )
        },
        bottomBar = {
            ChatInputBar(
                inputText = inputText,
                onInputChange = { viewModel.updateInput(it) },
                onPickImage = { imagePickerLauncher.launch("image/*") },
                onTakePhoto = {
                    val imageDir = File(context.cacheDir, "chat_images").apply { mkdirs() }
                    val imageFile = File(imageDir, "chat_${System.currentTimeMillis()}.jpg")
                    val uri = FileProvider.getUriForFile(
                        context,
                        "${context.packageName}.fileprovider",
                        imageFile
                    )
                    pendingCameraUri = uri
                    cameraLauncher.launch(uri)
                },
                onVoiceInput = {
                    if (ContextCompat.checkSelfPermission(context, Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED) {
                        startVoiceRecognition()
                    } else {
                        audioPermissionLauncher.launch(Manifest.permission.RECORD_AUDIO)
                    }
                },
                isListening = isListening,
                onSend = { viewModel.sendMessage(inputText) }
            )
        }
    ) { paddingValues ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(paddingValues)
                .background(MaterialTheme.colorScheme.background)
                .imePadding()
        ) {
            // Quick suggestions shown only when conversation just started
            AnimatedVisibility(
                visible = messages.size <= 1,
                enter = fadeIn() + slideInVertically()
            ) {
                Column(modifier = Modifier.padding(horizontal = 12.dp, vertical = 8.dp)) {
                    Text(
                        text = "快捷提问",
                        style = MaterialTheme.typography.labelMedium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        modifier = Modifier.padding(bottom = 6.dp)
                    )
                    LazyRow(
                        horizontalArrangement = Arrangement.spacedBy(8.dp)
                    ) {
                        items(MockData.quickSuggestions) { suggestion ->
                            SuggestionChip(
                                onClick = { viewModel.sendMessage(suggestion) },
                                label = {
                                    Text(
                                        text = suggestion,
                                        style = MaterialTheme.typography.bodySmall
                                    )
                                },
                                colors = SuggestionChipDefaults.suggestionChipColors(
                                    containerColor = MaterialTheme.colorScheme.primaryContainer,
                                    labelColor = MaterialTheme.colorScheme.primary
                                ),
                                shape = RoundedCornerShape(20.dp)
                            )
                        }
                    }
                }
            }

            // Messages list (reversed so newest at bottom)
            LazyColumn(
                modifier = Modifier
                    .fillMaxWidth()
                    .weight(1f),
                state = listState,
                reverseLayout = true,
                contentPadding = PaddingValues(vertical = 8.dp)
            ) {
                // Typing indicator at position 0 (visually at the bottom because reversed)
                if (isTyping) {
                    item(key = "typing_indicator") {
                        TypingIndicator()
                    }
                }

                // Messages in reverse order (newest first in the data source)
                items(
                    items = messages.reversed(),
                    key = { it.id }
                ) { message ->
                    ChatBubble(
                        message = message,
                        onProductClick = { productId ->
                            navController.navigate(Screen.ProductDetail.createRoute(productId))
                        },
                        onAddToCart = { productId -> viewModel.requestAddToCart(productId) },
                        onOpenCart = {
                            navController.navigate(Screen.Cart.route) {
                                launchSingleTop = true
                            }
                        },
                        onSpeak = { assistantMessage ->
                            speakAssistantMessage(assistantMessage.id, assistantMessage.content)
                        },
                        onStopSpeaking = { stopAssistantSpeech() },
                        isSpeaking = speakingMessageId == message.id,
                        onActionClick = { action ->
                            when (action.type) {
                                "go_detail" -> action.productId?.let { productId ->
                                    navController.navigate(Screen.ProductDetail.createRoute(productId))
                                }
                                "add_to_cart" -> action.productId?.let { productId ->
                                    viewModel.requestAddToCart(productId)
                                }
                                "open_cart" -> {
                                    navController.navigate(Screen.Cart.route) {
                                        launchSingleTop = true
                                    }
                                }
                                "search_more" -> {
                                    if (action.label == "修改收货地址") {
                                        navController.navigate(Screen.Addresses.route) {
                                            launchSingleTop = true
                                        }
                                    } else {
                                        viewModel.sendMessage(action.label)
                                    }
                                }
                            }
                        }
                    )
                }
            }
        }
    }
}

@Composable
private fun TypingIndicator() {
    val infiniteTransition = rememberInfiniteTransition(label = "typing")

    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = 12.dp, vertical = 4.dp),
        horizontalArrangement = Arrangement.Start,
        verticalAlignment = Alignment.CenterVertically
    ) {
        Spacer(modifier = Modifier.width(40.dp)) // Align with AI bubble (avatar width + spacing)

        Box(
            modifier = Modifier
                .background(
                    color = MaterialTheme.colorScheme.surfaceVariant,
                    shape = RoundedCornerShape(16.dp, 16.dp, 16.dp, 4.dp)
                )
                .padding(horizontal = 16.dp, vertical = 12.dp)
        ) {
            Row(
                horizontalArrangement = Arrangement.spacedBy(4.dp),
                verticalAlignment = Alignment.CenterVertically
            ) {
                repeat(3) { index ->
                    val alpha by infiniteTransition.animateFloat(
                        initialValue = 0.3f,
                        targetValue = 1f,
                        animationSpec = infiniteRepeatable(
                            animation = tween(600, delayMillis = index * 200),
                            repeatMode = RepeatMode.Reverse
                        ),
                        label = "dot_$index"
                    )
                    Box(
                        modifier = Modifier
                            .size(8.dp)
                            .clip(CircleShape)
                            .background(Primary.copy(alpha = alpha))
                    )
                }
            }
        }
    }
}

@Composable
private fun ChatInputBar(
    inputText: String,
    onInputChange: (String) -> Unit,
    onPickImage: () -> Unit,
    onTakePhoto: () -> Unit,
    onVoiceInput: () -> Unit,
    isListening: Boolean,
    onSend: () -> Unit
) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .background(MaterialTheme.colorScheme.surface)
            .padding(horizontal = 12.dp, vertical = 8.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(8.dp)
    ) {
        IconButton(
            onClick = onPickImage,
            modifier = Modifier.size(40.dp)
        ) {
            Icon(
                imageVector = Icons.Default.Image,
                contentDescription = "选择图片",
                tint = MaterialTheme.colorScheme.primary
            )
        }

        IconButton(
            onClick = onTakePhoto,
            modifier = Modifier.size(40.dp)
        ) {
            Icon(
                imageVector = Icons.Default.PhotoCamera,
                contentDescription = "拍照",
                tint = MaterialTheme.colorScheme.primary
            )
        }

        IconButton(
            onClick = onVoiceInput,
            modifier = Modifier.size(40.dp)
        ) {
            Icon(
                imageVector = Icons.Default.Mic,
                contentDescription = if (isListening) "正在听" else "语音输入",
                tint = if (isListening) Primary else MaterialTheme.colorScheme.primary
            )
        }

        TextField(
            value = inputText,
            onValueChange = onInputChange,
            modifier = Modifier.weight(1f),
            placeholder = {
                Text(
                    text = "输入你的问题...",
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.6f)
                )
            },
            shape = RoundedCornerShape(24.dp),
            colors = TextFieldDefaults.colors(
                focusedContainerColor = MaterialTheme.colorScheme.surfaceVariant,
                unfocusedContainerColor = MaterialTheme.colorScheme.surfaceVariant,
                focusedIndicatorColor = Color.Transparent,
                unfocusedIndicatorColor = Color.Transparent,
                disabledIndicatorColor = Color.Transparent
            ),
            singleLine = false,
            maxLines = 4,
            textStyle = MaterialTheme.typography.bodyMedium
        )

        IconButton(
            onClick = onSend,
            modifier = Modifier
                .size(44.dp)
                .clip(CircleShape)
                .background(
                    if (inputText.isNotBlank()) Primary else Primary.copy(alpha = 0.4f)
                ),
            enabled = inputText.isNotBlank()
        ) {
            Icon(
                imageVector = Icons.Default.ArrowUpward,
                contentDescription = "发送",
                tint = Color.White,
                modifier = Modifier.size(22.dp)
            )
        }
    }
}
