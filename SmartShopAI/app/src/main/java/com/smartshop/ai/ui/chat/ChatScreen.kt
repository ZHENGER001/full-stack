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
import android.content.Intent
import android.content.pm.PackageManager
import android.media.MediaRecorder
import android.net.Uri
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.speech.RecognitionListener
import android.speech.RecognizerIntent
import android.speech.SpeechRecognizer
import android.speech.tts.TextToSpeech
import android.speech.tts.UtteranceProgressListener
import androidx.compose.foundation.background
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.interaction.collectIsPressedAsState
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.ArrowUpward
import androidx.compose.material.icons.filled.Image
import androidx.compose.material.icons.filled.Mic
import androidx.compose.material.icons.filled.PhotoCamera
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.Checkbox
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SheetState
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.SuggestionChip
import androidx.compose.material3.SuggestionChipDefaults
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TextField
import androidx.compose.material3.TextFieldDefaults
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.material3.rememberModalBottomSheetState
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
import androidx.compose.ui.platform.LocalFocusManager
import androidx.compose.ui.platform.LocalSoftwareKeyboardController
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.core.content.FileProvider
import androidx.core.content.ContextCompat
import androidx.navigation.NavController
import com.smartshop.ai.data.mock.MockData
import com.smartshop.ai.data.model.ShippingAddress
import com.smartshop.ai.ui.components.ChatBubble
import com.smartshop.ai.ui.navigation.Screen
import com.smartshop.ai.ui.theme.Primary
import java.io.File
import java.util.Locale
import kotlinx.coroutines.launch

private const val TTS_UTTERANCE_PREFIX = "smartshop_tts_"

private enum class VoiceInputState {
    Idle,
    SystemListening,
    BackendRecording,
    Transcribing
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ChatScreen(
    navController: NavController,
    viewModel: ChatViewModel = hiltViewModel()
) {
    val messages by viewModel.messages.collectAsState()
    val inputText by viewModel.inputText.collectAsState()
    val isTyping by viewModel.isTyping.collectAsState()
    val addressUiState by viewModel.addressUiState.collectAsState()
    val listState = rememberLazyListState()
    val addressSheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true)
    val snackbarHostState = remember { SnackbarHostState() }
    val context = LocalContext.current
    val focusManager = LocalFocusManager.current
    val keyboardController = LocalSoftwareKeyboardController.current
    val coroutineScope = rememberCoroutineScope()
    val mainHandler = remember { Handler(Looper.getMainLooper()) }
    var pendingCameraUri by remember { mutableStateOf<Uri?>(null) }
    var voiceInputState by remember { mutableStateOf(VoiceInputState.Idle) }
    var speechRecognizer by remember { mutableStateOf<SpeechRecognizer?>(null) }
    var backendRecorder by remember { mutableStateOf<MediaRecorder?>(null) }
    var backendAudioFile by remember { mutableStateOf<File?>(null) }
    var preferBackendVoice by remember { mutableStateOf(false) }
    var textToSpeech by remember { mutableStateOf<TextToSpeech?>(null) }
    var isTtsReady by remember { mutableStateOf(false) }
    var speakingMessageId by remember { mutableStateOf<String?>(null) }
    var shouldAutoSpeakVoiceReply by remember { mutableStateOf(false) }
    var voiceRequestStartedAt by remember { mutableStateOf<Long?>(null) }
    var showAddressSheet by remember { mutableStateOf(false) }
    var refreshCheckoutAfterAddressSave by remember { mutableStateOf(false) }

    fun hideKeyboard() {
        keyboardController?.hide()
        focusManager.clearFocus()
    }

    fun openAddressSheet(refreshCheckoutAfterSave: Boolean) {
        hideKeyboard()
        refreshCheckoutAfterAddressSave = refreshCheckoutAfterSave
        showAddressSheet = true
        viewModel.loadAddresses()
    }

    fun sendChatMessage(text: String = inputText) {
        if (text.isBlank()) return
        hideKeyboard()
        viewModel.sendMessage(text)
    }

    fun createChatCameraUri(): Uri {
        val imageDir = File(context.cacheDir, "chat_images").apply { mkdirs() }
        val imageFile = File(imageDir, "chat_${System.currentTimeMillis()}.jpg")
        return FileProvider.getUriForFile(
            context,
            "${context.packageName}.fileprovider",
            imageFile
        )
    }

    fun launchChatCamera(cameraLauncher: androidx.activity.result.ActivityResultLauncher<Uri>) {
        val uri = createChatCameraUri()
        pendingCameraUri = uri
        cameraLauncher.launch(uri)
    }

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

    DisposableEffect(Unit) {
        onDispose {
            speechRecognizer?.destroy()
            speechRecognizer = null
            runCatching { backendRecorder?.stop() }
            backendRecorder?.release()
            backendRecorder = null
            backendAudioFile?.delete()
            backendAudioFile = null
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

    fun sendRecognizedVoice(text: String) {
        val spokenText = text.trim()
        if (spokenText.isBlank()) {
            coroutineScope.launch { snackbarHostState.showSnackbar("没有识别到语音，请再试一次") }
            return
        }
        stopAssistantSpeech()
        voiceRequestStartedAt = System.currentTimeMillis()
        shouldAutoSpeakVoiceReply = true
        hideKeyboard()
        viewModel.sendMessage(spokenText)
    }

    fun releaseSystemRecognition(cancel: Boolean) {
        if (cancel) {
            speechRecognizer?.cancel()
        }
        speechRecognizer?.destroy()
        speechRecognizer = null
        voiceInputState = VoiceInputState.Idle
    }

    fun stopSystemRecognition() {
        releaseSystemRecognition(cancel = true)
    }

    fun stopBackendRecordingAndTranscribe() {
        val recorder = backendRecorder
        val audioFile = backendAudioFile
        backendRecorder = null
        backendAudioFile = null

        val stopSucceeded = runCatching { recorder?.stop() }.isSuccess
        recorder?.release()

        if (!stopSucceeded || audioFile == null || !audioFile.exists() || audioFile.length() < 1024L) {
            audioFile?.delete()
            voiceInputState = VoiceInputState.Idle
            coroutineScope.launch { snackbarHostState.showSnackbar("录音太短或保存失败，请再试一次") }
            return
        }

        voiceInputState = VoiceInputState.Transcribing
        coroutineScope.launch { snackbarHostState.showSnackbar("正在转写语音...") }
        coroutineScope.launch {
            val result = viewModel.transcribeVoice(Uri.fromFile(audioFile))
            audioFile.delete()
            voiceInputState = VoiceInputState.Idle
            if (result.text.isNotBlank()) {
                sendRecognizedVoice(result.text)
            } else {
                snackbarHostState.showSnackbar(result.errorMessage ?: "语音转写失败，请重新输入")
            }
        }
    }

    fun startBackendRecording() {
        val audioDir = File(context.cacheDir, "voice_inputs").apply { mkdirs() }
        val audioFile = File(audioDir, "voice_${System.currentTimeMillis()}.aac")
        val recorder = createVoiceRecorder(audioFile)
        runCatching {
            recorder.prepare()
            recorder.start()
        }.onSuccess {
            backendRecorder = recorder
            backendAudioFile = audioFile
            voiceInputState = VoiceInputState.BackendRecording
            coroutineScope.launch { snackbarHostState.showSnackbar("正在录音，再点一次麦克风结束") }
        }.onFailure {
            recorder.release()
            audioFile.delete()
            voiceInputState = VoiceInputState.Idle
            coroutineScope.launch { snackbarHostState.showSnackbar("无法启动录音，请检查麦克风权限") }
        }
    }

    fun startSystemRecognition(): Boolean {
        if (!SpeechRecognizer.isRecognitionAvailable(context)) {
            return false
        }

        val recognizer = SpeechRecognizer.createSpeechRecognizer(context.applicationContext)
        speechRecognizer = recognizer
        recognizer.setRecognitionListener(object : RecognitionListener {
            override fun onReadyForSpeech(params: Bundle?) = Unit
            override fun onBeginningOfSpeech() = Unit
            override fun onRmsChanged(rmsdB: Float) = Unit
            override fun onBufferReceived(buffer: ByteArray?) = Unit
            override fun onEndOfSpeech() = Unit
            override fun onPartialResults(partialResults: Bundle?) = Unit
            override fun onEvent(eventType: Int, params: Bundle?) = Unit

            override fun onResults(results: Bundle?) {
                val spokenText = results
                    ?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)
                    ?.firstOrNull()
                    .orEmpty()
                releaseSystemRecognition(cancel = false)
                sendRecognizedVoice(spokenText)
            }

            override fun onError(error: Int) {
                releaseSystemRecognition(cancel = false)
                if (error == SpeechRecognizer.ERROR_NO_MATCH || error == SpeechRecognizer.ERROR_SPEECH_TIMEOUT) {
                    coroutineScope.launch { snackbarHostState.showSnackbar("没有识别到语音，请再试一次") }
                } else {
                    preferBackendVoice = true
                    coroutineScope.launch {
                        snackbarHostState.showSnackbar("系统语音识别不可用，再点麦克风将使用后端转写")
                    }
                }
            }
        })

        val intent = Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH).apply {
            putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
            putExtra(RecognizerIntent.EXTRA_LANGUAGE, Locale.getDefault())
            putExtra(RecognizerIntent.EXTRA_PARTIAL_RESULTS, false)
        }

        return runCatching {
            voiceInputState = VoiceInputState.SystemListening
            recognizer.startListening(intent)
            coroutineScope.launch { snackbarHostState.showSnackbar("正在识别语音...") }
        }.onFailure {
            releaseSystemRecognition(cancel = false)
        }.isSuccess
    }

    fun startVoiceInput() {
        when (voiceInputState) {
            VoiceInputState.SystemListening -> stopSystemRecognition()
            VoiceInputState.BackendRecording -> stopBackendRecordingAndTranscribe()
            VoiceInputState.Transcribing -> Unit
            VoiceInputState.Idle -> {
                val systemStarted = !preferBackendVoice && startSystemRecognition()
                if (!systemStarted) {
                    preferBackendVoice = true
                    startBackendRecording()
                }
            }
        }
    }

    val imagePickerLauncher = rememberLauncherForActivityResult(
        contract = ActivityResultContracts.GetContent()
    ) { uri ->
        uri?.let {
            hideKeyboard()
            viewModel.sendMessage(imageUri = it)
        }
    }
    val cameraLauncher = rememberLauncherForActivityResult(
        contract = ActivityResultContracts.TakePicture()
    ) { success ->
        if (success) {
            pendingCameraUri?.let {
                hideKeyboard()
                viewModel.sendMessage(imageUri = it)
            }
        } else {
            coroutineScope.launch { snackbarHostState.showSnackbar("未完成拍照") }
        }
        pendingCameraUri = null
    }
    val cameraPermissionLauncher = rememberLauncherForActivityResult(
        contract = ActivityResultContracts.RequestPermission()
    ) { granted ->
        if (granted) {
            launchChatCamera(cameraLauncher)
        } else {
            coroutineScope.launch { snackbarHostState.showSnackbar("需要相机权限才能拍照") }
        }
    }
    val audioPermissionLauncher = rememberLauncherForActivityResult(
        contract = ActivityResultContracts.RequestPermission()
    ) { granted ->
        if (granted) {
            startVoiceInput()
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

    if (showAddressSheet) {
        ChatAddressManagementSheet(
            sheetState = addressSheetState,
            uiState = addressUiState,
            onDismiss = {
                showAddressSheet = false
                refreshCheckoutAfterAddressSave = false
            },
            onOpenFullAddressPage = {
                showAddressSheet = false
                refreshCheckoutAfterAddressSave = false
                navController.navigate(Screen.Addresses.route) {
                    launchSingleTop = true
                }
            },
            onSave = { receiver, phone, province, city, district, detail, isDefault ->
                viewModel.addAddress(
                    receiverName = receiver,
                    phone = phone,
                    province = province,
                    city = city,
                    district = district,
                    detail = detail,
                    isDefault = isDefault
                ) {
                    showAddressSheet = false
                    if (refreshCheckoutAfterAddressSave) {
                        refreshCheckoutAfterAddressSave = false
                        viewModel.sendMessage(text = "结算", displayText = "已更新收货地址")
                    }
                }
            }
        )
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
                    if (ContextCompat.checkSelfPermission(context, Manifest.permission.CAMERA) == PackageManager.PERMISSION_GRANTED) {
                        launchChatCamera(cameraLauncher)
                    } else {
                        cameraPermissionLauncher.launch(Manifest.permission.CAMERA)
                    }
                },
                onVoiceInput = {
                    if (ContextCompat.checkSelfPermission(context, Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED) {
                        startVoiceInput()
                    } else {
                        audioPermissionLauncher.launch(Manifest.permission.RECORD_AUDIO)
                    }
                },
                voiceInputState = voiceInputState,
                onSend = { sendChatMessage() }
            )
        }
    ) { paddingValues ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(paddingValues)
                .background(MaterialTheme.colorScheme.background)
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
                                onClick = { sendChatMessage(suggestion) },
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
                        onBatchCartConfirm = { batchCart, selectedSkuIds ->
                            hideKeyboard()
                            viewModel.confirmBatchCart(batchCart, selectedSkuIds)
                        },
                        onOpenCart = {
                            navController.navigate(Screen.Cart.route) {
                                launchSingleTop = true
                            }
                        },
                        onOpenOrders = {
                            navController.navigate(Screen.Orders.route) {
                                launchSingleTop = true
                            }
                        },
                        onContinueShopping = {
                            navController.navigate(Screen.Home.route) {
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
                                    if (action.label == "修改收货地址" || action.label == "修改地址") {
                                        openAddressSheet(refreshCheckoutAfterSave = true)
                                    } else {
                                        sendChatMessage(action.label)
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

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun ChatAddressManagementSheet(
    sheetState: SheetState,
    uiState: ChatAddressUiState,
    onDismiss: () -> Unit,
    onOpenFullAddressPage: () -> Unit,
    onSave: (String, String, String, String, String, String, Boolean) -> Unit
) {
    ModalBottomSheet(
        onDismissRequest = onDismiss,
        sheetState = sheetState
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .fillMaxHeight(0.88f)
                .verticalScroll(rememberScrollState())
                .padding(horizontal = 18.dp, vertical = 8.dp),
            verticalArrangement = Arrangement.spacedBy(14.dp)
        ) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                verticalAlignment = Alignment.CenterVertically
            ) {
                Column(modifier = Modifier.weight(1f)) {
                    Text(
                        text = "修改收货地址",
                        style = MaterialTheme.typography.titleLarge,
                        fontWeight = FontWeight.Bold
                    )
                    Text(
                        text = "保存后将作为本次下单默认地址",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant
                    )
                }
                TextButton(onClick = onDismiss) {
                    Text("关闭")
                }
            }

            Button(
                onClick = onOpenFullAddressPage,
                modifier = Modifier.fillMaxWidth()
            ) {
                Text("进入地址管理页")
            }

            when {
                uiState.isLoading -> Text(
                    text = "正在加载地址...",
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
                uiState.addresses.isEmpty() -> Text(
                    text = "暂无收货地址",
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
                else -> {
                    Text(
                        text = "当前地址",
                        style = MaterialTheme.typography.labelLarge,
                        fontWeight = FontWeight.SemiBold
                    )
                    uiState.addresses.forEach { address ->
                        ChatAddressCard(address = address)
                    }
                }
            }

            if (!uiState.errorMessage.isNullOrBlank()) {
                Text(
                    text = uiState.errorMessage,
                    color = MaterialTheme.colorScheme.error,
                    style = MaterialTheme.typography.bodySmall
                )
            }

            ChatAddressForm(
                isSaving = uiState.isSaving,
                onSave = onSave
            )
            Spacer(modifier = Modifier.height(10.dp))
        }
    }
}

@Composable
private fun ChatAddressCard(address: ShippingAddress) {
    Card(
        modifier = Modifier.fillMaxWidth(),
        shape = RoundedCornerShape(10.dp),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.55f))
    ) {
        Column(
            modifier = Modifier.padding(12.dp),
            verticalArrangement = Arrangement.spacedBy(4.dp)
        ) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(
                    text = address.receiverName,
                    style = MaterialTheme.typography.bodyMedium,
                    fontWeight = FontWeight.SemiBold
                )
                Spacer(modifier = Modifier.width(8.dp))
                Text(
                    text = address.phone,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
                Spacer(modifier = Modifier.weight(1f))
                if (address.isDefault) {
                    Text(
                        text = "默认",
                        style = MaterialTheme.typography.labelMedium,
                        color = Primary
                    )
                }
            }
            Text(
                text = address.fullText,
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
        }
    }
}

@Composable
private fun ChatAddressForm(
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

    Card(
        modifier = Modifier.fillMaxWidth(),
        shape = RoundedCornerShape(12.dp),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface)
    ) {
        Column(
            modifier = Modifier.padding(14.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp)
        ) {
            Text(
                text = "新增地址",
                style = MaterialTheme.typography.labelLarge,
                fontWeight = FontWeight.SemiBold
            )
            OutlinedTextField(
                value = receiver,
                onValueChange = { receiver = it },
                label = { Text("收货人") },
                singleLine = true,
                modifier = Modifier.fillMaxWidth()
            )
            OutlinedTextField(
                value = phone,
                onValueChange = { phone = it },
                label = { Text("手机号") },
                singleLine = true,
                modifier = Modifier.fillMaxWidth()
            )
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedTextField(
                    value = province,
                    onValueChange = { province = it },
                    label = { Text("省") },
                    singleLine = true,
                    modifier = Modifier.weight(1f)
                )
                OutlinedTextField(
                    value = city,
                    onValueChange = { city = it },
                    label = { Text("市") },
                    singleLine = true,
                    modifier = Modifier.weight(1f)
                )
            }
            OutlinedTextField(
                value = district,
                onValueChange = { district = it },
                label = { Text("区") },
                singleLine = true,
                modifier = Modifier.fillMaxWidth()
            )
            OutlinedTextField(
                value = detail,
                onValueChange = { detail = it },
                label = { Text("详细地址") },
                modifier = Modifier.fillMaxWidth()
            )
            Row(verticalAlignment = Alignment.CenterVertically) {
                Checkbox(checked = isDefault, onCheckedChange = { isDefault = it })
                Text("设为默认地址")
            }
            Button(
                onClick = {
                    onSave(
                        receiver.trim(),
                        phone.trim(),
                        province.trim(),
                        city.trim(),
                        district.trim(),
                        detail.trim(),
                        isDefault
                    )
                },
                enabled = !isSaving &&
                    receiver.isNotBlank() &&
                    phone.isNotBlank() &&
                    province.isNotBlank() &&
                    city.isNotBlank() &&
                    district.isNotBlank() &&
                    detail.isNotBlank(),
                modifier = Modifier.fillMaxWidth()
            ) {
                Text(if (isSaving) "保存中..." else "保存地址")
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
    voiceInputState: VoiceInputState,
    onSend: () -> Unit
) {
    val voiceInteractionSource = remember { MutableInteractionSource() }
    val isVoicePressed by voiceInteractionSource.collectIsPressedAsState()
    val isVoiceActive = isVoicePressed || voiceInputState != VoiceInputState.Idle
    val voiceContentDescription = when (voiceInputState) {
        VoiceInputState.Idle -> "语音输入"
        VoiceInputState.SystemListening -> "正在听"
        VoiceInputState.BackendRecording -> "结束录音"
        VoiceInputState.Transcribing -> "正在转写"
    }

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
            modifier = Modifier
                .size(40.dp)
                .clip(CircleShape)
                .background(if (isVoiceActive) Primary.copy(alpha = 0.12f) else Color.Transparent),
            interactionSource = voiceInteractionSource
        ) {
            VoiceButtonContent(
                isActive = isVoiceActive,
                contentDescription = voiceContentDescription
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

@Composable
private fun VoiceButtonContent(
    isActive: Boolean,
    contentDescription: String
) {
    if (!isActive) {
        Icon(
            imageVector = Icons.Default.Mic,
            contentDescription = contentDescription,
            tint = MaterialTheme.colorScheme.primary
        )
        return
    }

    val infiniteTransition = rememberInfiniteTransition(label = "voice_wave")
    val peakHeights = listOf(12f, 20f, 28f, 20f, 12f)

    Row(
        modifier = Modifier
            .size(width = 26.dp, height = 28.dp)
            .semantics { this.contentDescription = contentDescription },
        horizontalArrangement = Arrangement.spacedBy(2.dp),
        verticalAlignment = Alignment.CenterVertically
    ) {
        peakHeights.forEachIndexed { index, peakHeight ->
            val barHeight by infiniteTransition.animateFloat(
                initialValue = 7f,
                targetValue = peakHeight,
                animationSpec = infiniteRepeatable(
                    animation = tween(durationMillis = 420 + index * 45, delayMillis = index * 70),
                    repeatMode = RepeatMode.Reverse
                ),
                label = "voice_wave_$index"
            )
            Box(
                modifier = Modifier
                    .width(3.dp)
                    .height(barHeight.dp)
                    .clip(RoundedCornerShape(2.dp))
                    .background(Primary)
            )
        }
    }
}

@Suppress("DEPRECATION")
private fun createVoiceRecorder(outputFile: File): MediaRecorder =
    MediaRecorder().apply {
        setAudioSource(MediaRecorder.AudioSource.MIC)
        setOutputFormat(MediaRecorder.OutputFormat.AAC_ADTS)
        setAudioEncoder(MediaRecorder.AudioEncoder.AAC)
        setAudioEncodingBitRate(128_000)
        setAudioSamplingRate(44_100)
        setOutputFile(outputFile.absolutePath)
    }
