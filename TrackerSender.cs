using UnityEngine;
using Unity.WebRTC;
using System.Collections.Generic;
using System.Text;
using UnityEngine.XR;

public class TrackerSender : MonoBehaviour
{
    public RTCDataChannel channel;
    static readonly List<XRNodeState> nodes = new();

    // -------------------- Conversões --------------------

    float[] MatrixToArray(Matrix4x4 m)
    {
        return new float[]
        {
            m.m00, m.m10, m.m20, m.m30,
            m.m01, m.m11, m.m21, m.m31,
            m.m02, m.m12, m.m22, m.m32,
            m.m03, m.m13, m.m23, m.m33
        };
    }

    Matrix4x4 PoseToMatrix(Vector3 pos, Quaternion rot)
    {
        return Matrix4x4.TRS(pos, rot, Vector3.one);
    }

    Matrix4x4 ConvertMatrix(Matrix4x4 m)
    {
        // flip eixo Z (Unity -> OpenXR / MuJoCo)
        Matrix4x4 flipZ = Matrix4x4.Scale(new Vector3(1, 1, -1));
        return flipZ * m * flipZ;
    }

    public void SetChannel(RTCDataChannel ch)
    {
        channel = ch;
    }

    // -------------------- Update --------------------

    void Update()
    {
        if (channel == null || channel.ReadyState != RTCDataChannelState.Open)
            return;

        InputTracking.GetNodeStates(nodes);

        Vector3 headPos = Vector3.zero;
        Quaternion headRot = Quaternion.identity;
        Vector3 leftPos = Vector3.zero;
        Quaternion leftRot = Quaternion.identity;
        Vector3 rightPos = Vector3.zero;
        Quaternion rightRot = Quaternion.identity;

        foreach (var n in nodes)
        {
            if (n.nodeType == XRNode.Head)
            {
                n.TryGetPosition(out headPos);
                n.TryGetRotation(out headRot);
            }
            else if (n.nodeType == XRNode.LeftHand)
            {
                n.TryGetPosition(out leftPos);
                n.TryGetRotation(out leftRot);
            }
            else if (n.nodeType == XRNode.RightHand)
            {
                n.TryGetPosition(out rightPos);
                n.TryGetRotation(out rightRot);
            }
        }

        Matrix4x4 headMat = ConvertMatrix(PoseToMatrix(headPos, headRot));
        Matrix4x4 leftMat = ConvertMatrix(PoseToMatrix(leftPos, leftRot));
        Matrix4x4 rightMat = ConvertMatrix(PoseToMatrix(rightPos, rightRot));

        PosePacket packet = new PosePacket
        {
            head = MatrixToArray(headMat),
            left = MatrixToArray(leftMat),
            right = MatrixToArray(rightMat)
        };

        // 🔥 muito mais rápido que JsonUtility
        string json = JsonUtility.ToJson(packet);

        channel.Send(Encoding.UTF8.GetBytes(json));
        //Debug.Log("Pose enviada: " + json);
    }

    // -------------------- Struct --------------------

    [System.Serializable]
    public struct PosePacket
    {
        public float[] head;  // 16 floats
        public float[] left;  // 16 floats
        public float[] right; // 16 floats
    }
}