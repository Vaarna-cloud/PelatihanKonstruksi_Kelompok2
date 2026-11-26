using TMPro;
using UnityEngine;
using UnityEngine.UI;

namespace Kelompok2.Intelligence
{
    /// <summary>
    /// Menampilkan ukuran kelayakan secara langsung (Bagian 4.2 & 5.2.2)
    /// dan status keputusan kecerdasan menggunakan warna pokok Kelompok 2 (#E08A16).
    /// </summary>
    public class IntelligenceHudView : MonoBehaviour
    {
        [Header("Referensi Mesin Keputusan")]
        [SerializeField] private VoiceDecisionEngine decisionEngine;

        [Header("Elemen UI (Opsional sesuai susunan Canvas kelompok)")]
        [SerializeField] private Image confidenceFillBar;
        [SerializeField] private TMP_Text confidenceText;
        [SerializeField] private TMP_Text stateBadgeText;
        [SerializeField] private TMP_Text reasonText;
        [SerializeField] private TMP_Text linkStatusText;

        [Header("Palet Warna Kelompok 2 (#E08A16)")]
        [SerializeField] private Color primaryOrange = new Color32(0xE0, 0x8A, 0x16, 0xFF);
        [SerializeField] private Color readyGreen = new Color32(0x2E, 0xCC, 0x71, 0xFF);
        [SerializeField] private Color dangerRed = new Color32(0xE7, 0x4C, 0x3C, 0xFF);

        private void OnEnable()
        {
            if (decisionEngine != null)
            {
                decisionEngine.onDecisionEvaluated.AddListener(HandleDecisionEvaluated);
            }
        }

        private void OnDisable()
        {
            if (decisionEngine != null)
            {
                decisionEngine.onDecisionEvaluated.RemoveListener(HandleDecisionEvaluated);
            }
        }

        private void Update()
        {
            if (decisionEngine == null)
            {
                return;
            }

            if (linkStatusText != null)
            {
                linkStatusText.text = decisionEngine.IsLinkAlive ? "Lapis AI: TERHUBUNG" : "Lapis AI: TERPUTUS";
                linkStatusText.color = decisionEngine.IsLinkAlive ? readyGreen : dangerRed;
            }
        }

        private void HandleDecisionEvaluated(EvaluatedDecision decision)
        {
            if (confidenceFillBar != null)
            {
                confidenceFillBar.fillAmount = Mathf.Clamp01(decision.confidence);
                confidenceFillBar.color = decision.state == DecisionState.Executed
                    ? readyGreen
                    : (decision.state == DecisionState.LinkDisconnected || decision.state == DecisionState.SafetyBlocked
                        ? dangerRed
                        : primaryOrange);
            }

            if (confidenceText != null)
            {
                confidenceText.text = $"Kelayakan: {decision.confidence * 100f:F0}% | Margin: {decision.margin:F2} | SNR: {decision.snrDb:F1} dB";
            }

            if (stateBadgeText != null)
            {
                stateBadgeText.text = $"{decision.state} ({decision.intent})";
                stateBadgeText.color = decision.state == DecisionState.Executed ? readyGreen : primaryOrange;
            }

            if (reasonText != null)
            {
                reasonText.text = decision.reason;
            }
        }
    }
}
