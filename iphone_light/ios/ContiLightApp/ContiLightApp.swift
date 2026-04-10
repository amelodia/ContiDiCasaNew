import SwiftUI
import UIKit

@main
struct ContiLightApp: App {
    var body: some Scene {
        WindowGroup {
            ContentView()
                // Sfondo esplicito: su alcune combinazioni iOS 26 / SwiftUI la vista può risultare tutta bianca.
                .background(Color(uiColor: .systemGroupedBackground))
        }
    }
}
