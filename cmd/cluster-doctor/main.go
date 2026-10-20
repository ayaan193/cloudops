package main

import (
	"context"
	"encoding/json"
	"flag"
	"fmt"
	"os"

	corev1 "k8s.io/api/core/v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/client-go/kubernetes"
	"k8s.io/client-go/tools/clientcmd"
)

type NodeReport struct {
	Name  string `json:"name"`
	Ready bool   `json:"ready"`
}

type PodProblem struct {
	Name      string `json:"name"`
	Namespace string `json:"namespace"`
	Status    string `json:"status"`
	Issue     string `json:"issue"`
}

type Report struct {
	ClusterHealthy bool         `json:"cluster_healthy"`
	Namespace      string       `json:"namespace"`
	NodesTotal     int          `json:"nodes_total"`
	NodesReady     int          `json:"nodes_ready"`
	Nodes          []NodeReport `json:"nodes"`
	PodsInspected  int          `json:"pods_inspected"`
	ProblemsFound  int          `json:"problems_found"`
	Problems       []PodProblem `json:"problems"`
}

func main() {
	if err := run(); err != nil {
		fmt.Fprintln(os.Stderr, "cluster-doctor:", err)
		os.Exit(1)
	}
}

func run() error {
	namespace := flag.String(
		"namespace", "cloudops-lab",
		"Namespace to inspect for Pod problems",
	)
	jsonOutput := flag.Bool(
		"json", false,
		"Print the report as JSON",
	)
	flag.Parse()

	config, err := clientcmd.NewDefaultClientConfigLoadingRules().Load()
	if err != nil {
		return fmt.Errorf("load kubeconfig: %w", err)
	}

	restConfig, err := clientcmd.NewDefaultClientConfig(
		*config, &clientcmd.ConfigOverrides{},
	).ClientConfig()
	if err != nil {
		return fmt.Errorf("build Kubernetes config: %w", err)
	}

	clientset, err := kubernetes.NewForConfig(restConfig)
	if err != nil {
		return fmt.Errorf("create Kubernetes client: %w", err)
	}

	ctx := context.Background()

	nodes, err := clientset.CoreV1().Nodes().List(
		ctx, metav1.ListOptions{},
	)
	if err != nil {
		return fmt.Errorf("list nodes: %w", err)
	}

	pods, err := clientset.CoreV1().Pods(*namespace).List(
		ctx, metav1.ListOptions{},
	)
	if err != nil {
		return fmt.Errorf("list Pods in namespace %q: %w", *namespace, err)
	}

	report := Report{
		ClusterHealthy: len(nodes.Items) > 0,
		Namespace:      *namespace,
		NodesTotal:     len(nodes.Items),
		Nodes:          []NodeReport{},
		PodsInspected:  len(pods.Items),
		Problems:       []PodProblem{},
	}

	for _, node := range nodes.Items {
		ready := isNodeReady(node)
		report.Nodes = append(report.Nodes, NodeReport{
			Name: node.Name, Ready: ready,
		})

		if ready {
			report.NodesReady++
		} else {
			report.ClusterHealthy = false
		}
	}

	for _, pod := range pods.Items {
		issue := podIssue(pod)
		if issue == "" {
			continue
		}

		report.Problems = append(report.Problems, PodProblem{
			Name:      pod.Name,
			Namespace: pod.Namespace,
			Status:    string(pod.Status.Phase),
			Issue:     issue,
		})
	}

	report.ProblemsFound = len(report.Problems)

	if *jsonOutput {
		if err := json.NewEncoder(os.Stdout).Encode(report); err != nil {
			return fmt.Errorf("encode JSON report: %w", err)
		}
	} else {
		printReport(report)
	}

	if !report.ClusterHealthy {
		return fmt.Errorf("one or more cluster nodes are not Ready")
	}
	if report.ProblemsFound > 0 {
		return fmt.Errorf("diagnostics found %d problem(s)", report.ProblemsFound)
	}

	return nil
}

func printReport(report Report) {
	fmt.Println("Cluster Doctor — Health Report")
	fmt.Println("===============================")
	fmt.Println("\nNode Health")
	fmt.Println("-----------")

	for _, node := range report.Nodes {
		status := "NotReady"
		if node.Ready {
			status = "Ready"
		}
		fmt.Printf("%-35s %s\n", node.Name, status)
	}

	fmt.Printf("Nodes ready: %d/%d\n",
		report.NodesReady, report.NodesTotal)

	fmt.Printf("\nPod Diagnostics — namespace: %s\n", report.Namespace)
	fmt.Println("-----------------------------------------------")

	if report.ProblemsFound == 0 {
		fmt.Println("No unhealthy Pods detected.")
	} else {
		for _, problem := range report.Problems {
			fmt.Printf("[PROBLEM] %s status=%s issue=%s\n",
				problem.Name, problem.Status, problem.Issue)
		}
	}

	fmt.Printf("Pods inspected: %d | Problems found: %d\n",
		report.PodsInspected, report.ProblemsFound)
}

func isNodeReady(node corev1.Node) bool {
	for _, condition := range node.Status.Conditions {
		if condition.Type == corev1.NodeReady {
			return condition.Status == corev1.ConditionTrue
		}
	}
	return false
}

func podIssue(pod corev1.Pod) string {
	switch pod.Status.Phase {
	case corev1.PodFailed:
		return "PodFailed"
	case corev1.PodPending:
		return "PodPending"
	case corev1.PodUnknown:
		return "PodUnknown"
	}

	statusGroups := [][]corev1.ContainerStatus{
		pod.Status.InitContainerStatuses,
		pod.Status.ContainerStatuses,
	}

	for _, statuses := range statusGroups {
		for _, status := range statuses {
			if status.State.Waiting != nil {
				switch status.State.Waiting.Reason {
				case "ImagePullBackOff", "ErrImagePull",
					"CrashLoopBackOff", "CreateContainerConfigError",
					"CreateContainerError":
					return status.Name + ": " +
						status.State.Waiting.Reason
				}
			}

			if status.State.Terminated != nil &&
				status.State.Terminated.ExitCode != 0 {
				return fmt.Sprintf("%s exited with code %d",
					status.Name, status.State.Terminated.ExitCode)
			}
		}
	}

	for _, condition := range pod.Status.Conditions {
		if condition.Type == corev1.PodReady &&
			condition.Status == corev1.ConditionFalse &&
			pod.Status.Phase == corev1.PodRunning {
			return "PodNotReady"
		}
	}

	return ""
}
