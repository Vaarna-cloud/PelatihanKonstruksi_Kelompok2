using UnityEngine;
using UnityEngine.Events;

namespace Kelompok2.Intelligence
{
    /// <summary>
    /// Mesin pengambil keputusan komponen kecerdasan (Lapis Pemakai).
    /// Mengelola ukuran kelayakan, batas bertindak, histeresis/kestabilan,
    /// perilaku saat gagal atau terputus, serta jalan lain konvensional.
    /// </summary>
    public class VoiceDecisionEngine : MonoBehaviour
    {
        [Header("Referensi Penerima")]
        [SerializeField] private SignalReceiver signalReceiver;

        [Header("Batas Bertindak (Bagian 5.2.3)")]
        [Range(0f, 1f)]
        [SerializeField] private float acceptThreshold = 0.75f;
        [Range(0f, 1f)]
        [SerializeField] private float confirmThreshold = 0.55f;
        [Range(0f, 1f)]
        [SerializeField] private float minMargin = 0.15f;
        [SerializeField] private float minSnrDb = 6.0f;

        [Header("Kestabilan & Histeresis (Bagian 4.2 & 5.2.4)")]
        [SerializeField] private float commandCooldownSeconds = 1.5f;
        [SerializeField] private float confirmationWindowSeconds = 6.0f;
        [SerializeField] private bool requireConfirmationForLower = true;
        [Range(0f, 1f)]
        [Tooltip("Ambang lebih tinggi (histeresis) untuk melepas status TAHAN yang sedang aktif.")]
        [SerializeField] private float releaseHoldConfidence = 0.82f;

        [Header("Gerbang Syarat Keselamatan K3 (Diisi oleh Integrator / Collider)")]
        [SerializeField] private bool isSafetyHarnessAttached = true;
        [SerializeField] private bool isDropZoneClear = true;

        [Header("Jalan Lain Konvensional (Bagian 5.2.6)")]
        [SerializeField] private bool enableKeyboardFallback = true;

        [Header("Status Terkini (Read-Only)")]
        [SerializeField] private DecisionState currentState = DecisionState.Idle;
        [SerializeField] private ConstructionIntent activeIntent = ConstructionIntent.None;
        [SerializeField] private ConstructionIntent pendingIntent = ConstructionIntent.None;
        [SerializeField] private bool isEmergencyHoldLocked;
        [SerializeField] private float lastConfidence;
        [SerializeField] private float lastMargin;
        [SerializeField] private float lastSnrDb;
        [SerializeField] private float lastSignalLevel;
        [SerializeField] private string lastDecisionReason = "Menunggu masukan...";

        [Header("Event untuk Supervisor, Crane, & Antarmuka")]
        public UnityEvent<EvaluatedDecision> onDecisionEvaluated;
        public UnityEvent<ConstructionIntent> onIntentExecuted;
        public UnityEvent<ConstructionIntent, string> onIntentNeedsConfirmation;
        public UnityEvent<string> onIntentHeldBack;
        public UnityEvent<string> onSafetyGateBlocked;
        public UnityEvent onFailSafeHoldTriggered;

        private float _lastExecutedTime = -999f;
        private float _pendingStartTime = -999f;

        public DecisionState CurrentState => currentState;
        public ConstructionIntent ActiveIntent => activeIntent;
        public ConstructionIntent PendingIntent => pendingIntent;
        public float LastConfidence => lastConfidence;
        public float LastMargin => lastMargin;
        public float LastSnrDb => lastSnrDb;
        public float LastSignalLevel => lastSignalLevel;
        public string LastDecisionReason => lastDecisionReason;
        public bool IsLinkAlive => signalReceiver != null && signalReceiver.IsLinkAlive;
        public bool IsEmergencyHoldLocked => isEmergencyHoldLocked;

        private void Awake()
        {
            if (signalReceiver == null)
            {
                signalReceiver = GetComponent<SignalReceiver>();
            }
        }

        private void OnEnable()
        {
            if (signalReceiver != null)
            {
                signalReceiver.onPacketReceived.AddListener(HandlePacketReceived);
                signalReceiver.onLinkStatusChanged.AddListener(HandleLinkStatusChanged);
            }
        }

        private void OnDisable()
        {
            if (signalReceiver != null)
            {
                signalReceiver.onPacketReceived.RemoveListener(HandlePacketReceived);
                signalReceiver.onLinkStatusChanged.RemoveListener(HandleLinkStatusChanged);
            }
        }

        private void Update()
        {
            // Kedaluwarsa jendela konfirmasi otomatis agar perintah tertunda tidak nyangkut
            if (pendingIntent != ConstructionIntent.None &&
                Time.unscaledTime - _pendingStartTime > confirmationWindowSeconds)
            {
                ConstructionIntent expired = pendingIntent;
                pendingIntent = ConstructionIntent.None;
                EmitDecision(expired, DecisionState.HeldBack, false,
                    "Waktu konfirmasi habis, perintah dibatalkan demi keamanan.");
            }

            if (enableKeyboardFallback)
            {
                PollKeyboardFallback();
            }
        }

        /// <summary>
        /// Dipanggil oleh skrip kolider harness milik tim untuk memperbarui status K3.
        /// </summary>
        public void SetHarnessAttached(bool attached)
        {
            isSafetyHarnessAttached = attached;
        }

        /// <summary>
        /// Dipanggil oleh skrip zona bahaya di bawah muatan untuk memperbarui status K3.
        /// </summary>
        public void SetDropZoneClear(bool clear)
        {
            isDropZoneClear = clear;
        }

        /// <summary>
        /// Jalan lain (Bagian 5.2.6) untuk dipanggil langsung oleh tombol UI (1..5).
        /// </summary>
        public void TriggerFallbackByIndex(int intentIndex)
        {
            if (intentIndex < 1 || intentIndex > 5)
            {
                return;
            }

            TriggerFallbackIntent((ConstructionIntent)intentIndex);
        }

        /// <summary>
        /// Jalan lain (Bagian 5.2.6) menggunakan masukan konvensional yang pasti terbaca.
        /// </summary>
        public void TriggerFallbackIntent(ConstructionIntent intent)
        {
            lastConfidence = 1.0f;
            lastMargin = 1.0f;
            lastSnrDb = 25.0f;
            ExecuteValidatedIntent(intent, fromFallback: true);
        }

        private void PollKeyboardFallback()
        {
            if (Input.GetKeyDown(KeyCode.Alpha1)) TriggerFallbackIntent(ConstructionIntent.RaiseMaterial);
            else if (Input.GetKeyDown(KeyCode.Alpha2)) TriggerFallbackIntent(ConstructionIntent.LowerMaterial);
            else if (Input.GetKeyDown(KeyCode.Alpha3)) TriggerFallbackIntent(ConstructionIntent.EmergencyHold);
            else if (Input.GetKeyDown(KeyCode.Alpha4)) TriggerFallbackIntent(ConstructionIntent.CancelAction);
            else if (Input.GetKeyDown(KeyCode.Alpha5)) TriggerFallbackIntent(ConstructionIntent.ConfirmAction);
        }

        private void HandleLinkStatusChanged(bool alive)
        {
            if (!alive)
            {
                // Perilaku saat pelacakan terputus (Bagian 4.2): hentikan aksi secara aman (fail-safe)
                pendingIntent = ConstructionIntent.None;
                isEmergencyHoldLocked = true;
                activeIntent = ConstructionIntent.EmergencyHold;
                EmitDecision(ConstructionIntent.EmergencyHold, DecisionState.LinkDisconnected, false,
                    "Koneksi lapis kecerdasan terputus: sistem otomatis menahan gerakan (fail-safe).");
                onFailSafeHoldTriggered?.Invoke();
            }
            else
            {
                EmitDecision(activeIntent, DecisionState.Idle, false,
                    "Koneksi lapis kecerdasan tersambung kembali.");
            }
        }

        private void HandlePacketReceived(SignalPacket packet)
        {
            lastSignalLevel = packet.signal_level;
            lastSnrDb = packet.signal_to_noise_db;

            // Paket detak jantung hanya memperbarui sinyal hidup, bukan memicu perintah
            if (packet.heartbeat)
            {
                return;
            }

            lastConfidence = packet.confidence;
            lastMargin = packet.margin;

            ConstructionIntent mapped = MapTokenToIntent(packet.token);
            if (mapped == ConstructionIntent.None)
            {
                EmitDecision(ConstructionIntent.None, DecisionState.HeldBack, false,
                    $"Masukan '{packet.utterance}' tidak termasuk 5 kelas perintah; sistem menahan diri.");
                return;
            }

            // Cek batas kebisingan (SNR)
            if (packet.signal_to_noise_db < minSnrDb)
            {
                EmitDecision(mapped, DecisionState.HeldBack, false,
                    $"Kebisingan terlalu tinggi (SNR {packet.signal_to_noise_db:F1} dB < {minSnrDb:F1} dB).");
                return;
            }

            // Cek ukuran kelayakan minimum
            if (packet.confidence < confirmThreshold)
            {
                EmitDecision(mapped, DecisionState.HeldBack, false,
                    $"Keyakinan terlalu rendah ({packet.confidence:P0} < {confirmThreshold:P0}); sistem menahan diri.");
                return;
            }

            // Cek selisih skor dengan kandidat perintah lain
            if (packet.margin < minMargin)
            {
                EmitDecision(mapped, DecisionState.HeldBack, false,
                    $"Perintah ambigu (margin {packet.margin:F2} < {minMargin:F2}); sistem menahan diri.");
                return;
            }

            // Kestabilan: anti-kedip (cooldown) untuk mencegah pemicuan ganda, kecuali perintah henti/batal
            bool isSafetyStop = mapped == ConstructionIntent.EmergencyHold || mapped == ConstructionIntent.CancelAction;
            if (!isSafetyStop && Time.unscaledTime - _lastExecutedTime < commandCooldownSeconds)
            {
                EmitDecision(mapped, DecisionState.HeldBack, false,
                    "Masih dalam jeda kestabilan antar perintah.");
                return;
            }

            // Kestabilan histeresis: status TAHAN hanya boleh dilepas oleh keyakinan lebih tinggi atau konfirmasi
            if (isEmergencyHoldLocked &&
                (mapped == ConstructionIntent.RaiseMaterial || mapped == ConstructionIntent.LowerMaterial) &&
                packet.confidence < releaseHoldConfidence)
            {
                RequestConfirmation(mapped,
                    $"Status TAHAN aktif. Butuh keyakinan >= {releaseHoldConfidence:P0} atau ucapkan KONFIRMASI.");
                return;
            }

            // Zona abu-abu (antara confirmThreshold dan acceptThreshold) -> minta penegasan pengguna
            if (packet.confidence < acceptThreshold && !isSafetyStop)
            {
                RequestConfirmation(mapped,
                    $"Suara kurang tegas ({packet.confidence:P0}). Ucapkan KONFIRMASI atau BATAL.");
                return;
            }

            // Perintah berisiko tinggi (TURUN) butuh konfirmasi eksplisit bila diaktifkan
            if (requireConfirmationForLower &&
                mapped == ConstructionIntent.LowerMaterial &&
                pendingIntent != ConstructionIntent.LowerMaterial)
            {
                RequestConfirmation(mapped,
                    "Perintah TURUN berisiko tinggi: pastikan area bawah steril lalu ucapkan KONFIRMASI.");
                return;
            }

            ExecuteValidatedIntent(mapped, fromFallback: false);
        }

        private void RequestConfirmation(ConstructionIntent candidate, string reason)
        {
            pendingIntent = candidate;
            _pendingStartTime = Time.unscaledTime;
            EmitDecision(candidate, DecisionState.NeedsConfirmation, false, reason);
            onIntentNeedsConfirmation?.Invoke(candidate, reason);
        }

        private void ExecuteValidatedIntent(ConstructionIntent intent, bool fromFallback)
        {
            // Tangani konfirmasi atas perintah yang tertunda
            if (intent == ConstructionIntent.ConfirmAction)
            {
                if (pendingIntent == ConstructionIntent.None)
                {
                    EmitDecision(ConstructionIntent.ConfirmAction, DecisionState.HeldBack, fromFallback,
                        "Tidak ada perintah tertunda yang perlu dikonfirmasi.");
                    return;
                }

                intent = pendingIntent;
                pendingIntent = ConstructionIntent.None;
            }
            else if (intent == ConstructionIntent.CancelAction)
            {
                pendingIntent = ConstructionIntent.None;
                isEmergencyHoldLocked = false;
                activeIntent = ConstructionIntent.CancelAction;
                _lastExecutedTime = Time.unscaledTime;
                EmitDecision(ConstructionIntent.CancelAction, DecisionState.Executed, fromFallback,
                    "Perintah atau operasi dibatalkan oleh pekerja.");
                onIntentExecuted?.Invoke(ConstructionIntent.CancelAction);
                return;
            }
            else if (intent == ConstructionIntent.EmergencyHold)
            {
                pendingIntent = ConstructionIntent.None;
                isEmergencyHoldLocked = true;
                activeIntent = ConstructionIntent.EmergencyHold;
                _lastExecutedTime = Time.unscaledTime;
                EmitDecision(ConstructionIntent.EmergencyHold, DecisionState.Executed, fromFallback,
                    "Perintah TAHAN aktif: seluruh pergerakan dihentikan sementara.");
                onIntentExecuted?.Invoke(ConstructionIntent.EmergencyHold);
                return;
            }

            // Gerbang keselamatan K3 sebelum menggerakkan material (ANGKAT / TURUN)
            if (intent == ConstructionIntent.RaiseMaterial || intent == ConstructionIntent.LowerMaterial)
            {
                if (!isSafetyHarnessAttached)
                {
                    EmitDecision(intent, DecisionState.SafetyBlocked, fromFallback,
                        "Supervisor menolak: kaitkan safety harness terlebih dahulu.");
                    onSafetyGateBlocked?.Invoke(lastDecisionReason);
                    return;
                }

                if (intent == ConstructionIntent.LowerMaterial && !isDropZoneClear)
                {
                    EmitDecision(intent, DecisionState.SafetyBlocked, fromFallback,
                        "Supervisor menolak: area di bawah muatan belum steril.");
                    onSafetyGateBlocked?.Invoke(lastDecisionReason);
                    return;
                }
            }

            pendingIntent = ConstructionIntent.None;
            isEmergencyHoldLocked = false;
            activeIntent = intent;
            _lastExecutedTime = Time.unscaledTime;

            string sourceLabel = fromFallback ? "tombol jalan lain" : "suara jelas";
            EmitDecision(intent, DecisionState.Executed, fromFallback,
                $"Perintah {intent} dijalankan ({sourceLabel}).");
            onIntentExecuted?.Invoke(intent);
        }

        private void EmitDecision(
            ConstructionIntent intent,
            DecisionState state,
            bool fromFallback,
            string reason)
        {
            currentState = state;
            lastDecisionReason = reason;

            var summary = new EvaluatedDecision
            {
                intent = intent,
                state = state,
                confidence = lastConfidence,
                margin = lastMargin,
                snrDb = lastSnrDb,
                fromFallback = fromFallback,
                reason = reason
            };

            if (state == DecisionState.HeldBack)
            {
                onIntentHeldBack?.Invoke(reason);
            }

            onDecisionEvaluated?.Invoke(summary);
        }

        private static ConstructionIntent MapTokenToIntent(string token)
        {
            switch (token)
            {
                case "CMD_1": return ConstructionIntent.RaiseMaterial;
                case "CMD_2": return ConstructionIntent.LowerMaterial;
                case "CMD_3": return ConstructionIntent.EmergencyHold;
                case "CMD_4": return ConstructionIntent.CancelAction;
                case "CMD_5": return ConstructionIntent.ConfirmAction;
                default: return ConstructionIntent.None;
            }
        }
    }
}
