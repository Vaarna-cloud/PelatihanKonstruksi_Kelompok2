using UnityEngine;

namespace Kelompok2.Intelligence
{
    /// <summary>
    /// Skrip demo sementara untuk menguji respons kubus terhadap VoiceDecisionEngine
    /// sebelum digabungkan ke adegan crane kelompok.
    /// </summary>
    public class DummyCubeTester : MonoBehaviour
    {
        [Header("Referensi Mesin Keputusan")]
        [SerializeField] private VoiceDecisionEngine decisionEngine;

        [Header("Pengaturan Gerak Kubus Uji")]
        [SerializeField] private float moveSpeed = 1.5f;
        [SerializeField] private float minHeight = 0.5f;
        [SerializeField] private float maxHeight = 5.0f;

        private int _moveDirection; // 1 = naik, -1 = turun, 0 = berhenti
        private Renderer _cubeRenderer;

        private static readonly Color ColorOrange = new Color32(0xE0, 0x8A, 0x16, 0xFF);
        private static readonly Color ColorGreen = new Color32(0x2E, 0xCC, 0x71, 0xFF);
        private static readonly Color ColorRed = new Color32(0xE7, 0x4C, 0x3C, 0xFF);
        private static readonly Color ColorYellow = new Color32(0xF1, 0xC4, 0x0F, 0xFF);

        private void Awake()
        {
            _cubeRenderer = GetComponent<Renderer>();
            SetCubeColor(ColorOrange);
        }

        private void OnEnable()
        {
            if (decisionEngine == null)
            {
                return;
            }

            decisionEngine.onIntentExecuted.AddListener(HandleIntentExecuted);
            decisionEngine.onIntentNeedsConfirmation.AddListener(HandleNeedsConfirmation);
            decisionEngine.onIntentHeldBack.AddListener(HandleHeldBack);
            decisionEngine.onSafetyGateBlocked.AddListener(HandleSafetyBlocked);
            decisionEngine.onFailSafeHoldTriggered.AddListener(HandleFailSafe);
        }

        private void OnDisable()
        {
            if (decisionEngine == null)
            {
                return;
            }

            decisionEngine.onIntentExecuted.RemoveListener(HandleIntentExecuted);
            decisionEngine.onIntentNeedsConfirmation.RemoveListener(HandleNeedsConfirmation);
            decisionEngine.onIntentHeldBack.RemoveListener(HandleHeldBack);
            decisionEngine.onSafetyGateBlocked.RemoveListener(HandleSafetyBlocked);
            decisionEngine.onFailSafeHoldTriggered.RemoveListener(HandleFailSafe);
        }

        private void Update()
        {
            if (_moveDirection == 0)
            {
                return;
            }

            Vector3 pos = transform.position;
            pos.y = Mathf.Clamp(pos.y + _moveDirection * moveSpeed * Time.deltaTime, minHeight, maxHeight);
            transform.position = pos;

            if (pos.y <= minHeight || pos.y >= maxHeight)
            {
                _moveDirection = 0;
                SetCubeColor(ColorOrange);
            }
        }

        private void HandleIntentExecuted(ConstructionIntent intent)
        {
            Debug.Log($"[DummyDemo] DITERIMA & JALAN: {intent}");

            switch (intent)
            {
                case ConstructionIntent.RaiseMaterial:
                    _moveDirection = 1;
                    SetCubeColor(ColorGreen);
                    break;
                case ConstructionIntent.LowerMaterial:
                    _moveDirection = -1;
                    SetCubeColor(ColorGreen);
                    break;
                case ConstructionIntent.EmergencyHold:
                case ConstructionIntent.CancelAction:
                    _moveDirection = 0;
                    SetCubeColor(ColorRed);
                    break;
            }
        }

        private void HandleNeedsConfirmation(ConstructionIntent pendingIntent, string reason)
        {
            _moveDirection = 0;
            SetCubeColor(ColorYellow);
            Debug.LogWarning($"[DummyDemo] BUTUH KONFIRMASI ({pendingIntent}): {reason}");
        }

        private void HandleHeldBack(string reason)
        {
            Debug.Log($"[DummyDemo] MENAHAN DIRI: {reason}");
        }

        private void HandleSafetyBlocked(string reason)
        {
            _moveDirection = 0;
            SetCubeColor(ColorRed);
            Debug.LogWarning($"[DummyDemo] DIBLOKIR K3: {reason}");
        }

        private void HandleFailSafe()
        {
            _moveDirection = 0;
            SetCubeColor(ColorRed);
            Debug.LogError("[DummyDemo] KONEKSI TERPUTUS -> FAIL-SAFE BERHENTI!");
        }

        private void SetCubeColor(Color color)
        {
            if (_cubeRenderer != null)
            {
                _cubeRenderer.material.color = color;
            }
        }
    }
}
